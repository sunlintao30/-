#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频批量压缩器（PyQt5） - 带打包兼容与依赖检测（防闪退）
保存为 视频批量压缩器.py
打包示例：
pyinstaller -F -w --add-binary "ffmpeg.exe;." --add-binary "ffprobe.exe;." 视频批量压缩器.py
"""

import sys
import os
import json
import shutil
import threading
import subprocess
import re
from pathlib import Path
from datetime import datetime, timedelta
from queue import Queue
from typing import Optional

from PyQt5 import QtWidgets, QtCore, QtGui

# ---- 常量/预设 ----
VIDEO_EXTS = {'.mp4', '.mkv', '.mov', '.avi', '.flv', '.webm', '.ts', '.m4v'}
DEFAULT_PROGRESS = 'progress.json'
DEFAULT_APP_LOG = 'app.log'
CPU_PRESETS = ['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow']
NVENC_PRESETS = ['default', 'slow', 'medium', 'fast', 'hp', 'hq', 'll', 'llhq', 'llhp', 'lossless', 'losslesshp']

# ---- 正则 ----
PROGRESS_OUT_TIME_MS = re.compile(r'out_time_ms=(\d+)')
PROGRESS_OUT_TIME = re.compile(r'out_time=(\d+:\d+:\d+\.\d+)')

# ---- 工具函数 ----

def is_video_file(p: Path):
    return p.suffix.lower() in VIDEO_EXTS

def seconds_to_time_str(s: float) -> str:
    total_seconds = int(s or 0)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def time_str_to_seconds(t: str) -> float:
    try:
        parts = t.split(':')
        if len(parts) == 3:
            h, m, s = parts
            return float(h) * 3600 + float(m) * 60 + float(s)
        return float(t)
    except:
        return 0.0

def detect_tool(name: str) -> Optional[str]:
    """检测工具路径：优先 PATH；若为 PyInstaller 打包则优先临时解压目录；其次程序目录；找不到返回 None。"""
    # 1. PATH
    p = shutil.which(name)
    if p:
        return p
    # 2. PyInstaller 解压目录
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        mpath = Path(sys._MEIPASS) / f"{name}.exe"
        if mpath.exists():
            return str(mpath)
    # 3. 可执行所在目录（打包时用）
    base = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    local = base / f"{name}.exe"
    if local.exists():
        return str(local)
    return None

def ffmpeg_supports_codec(ffmpeg_path: str, codec_name: str) -> bool:
    try:
        proc = subprocess.run([ffmpeg_path, "-hide_banner", "-encoders"],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              encoding='utf-8', errors='ignore', timeout=10)
        return codec_name in proc.stdout
    except Exception:
        return False

def probe_duration(ffprobe_path: Optional[str], input_file: str) -> Optional[float]:
    if not ffprobe_path:
        return None
    try:
        cmd = [ffprobe_path, "-v", "error", "-show_entries", "format=duration", "-of",
               "default=noprint_wrappers=1:nokey=1", input_file]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              encoding='utf-8', errors='ignore', timeout=10)
        out = proc.stdout.strip()
        if out:
            try:
                return float(out)
            except:
                return None
        return None
    except Exception:
        return None

# ---- 数据库 ----

class ProgressDBLocal:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.lock = threading.Lock()
        self.data = {'files': {}}
        if db_path.exists():
            try:
                self._load()
            except Exception:
                backup = db_path.with_suffix('.bak.json')
                try:
                    db_path.rename(backup)
                except:
                    pass
                self.data = {'files': {}}
                self._save()

    def _load(self):
        with self.db_path.open('r', encoding='utf-8') as f:
            self.data = json.load(f)

    def _save(self):
        tmp = self.db_path.with_suffix('.tmp.json')
        with tmp.open('w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        tmp.replace(self.db_path)

    def update_file_status(self, src, status, **kwargs):
        with self.lock:
            info = self.data['files'].get(src, {})
            info.update({'status': status, 'last_update': datetime.utcnow().isoformat()})
            info.update(kwargs)
            self.data['files'][src] = info
            self._save()

    def add_file(self, src):
        with self.lock:
            if src not in self.data['files']:
                self.data['files'][src] = {'status': 'pending', 'added': datetime.utcnow().isoformat()}
                self._save()

    def all(self):
        return dict(self.data['files'])

# ---- 后台 Worker ----

class CompressorWorker(QtCore.QObject):
    progress_signal = QtCore.pyqtSignal(str, int, float, float)
    status_signal = QtCore.pyqtSignal(str, str)
    log_signal = QtCore.pyqtSignal(str)

    def __init__(self, task_queue: Queue, db: ProgressDBLocal, settings: dict, stop_event: threading.Event):
        super().__init__()
        self.task_queue = task_queue
        self.db = db
        self.settings = settings
        self.stop_event = stop_event
        # detect tools
        self.ffmpeg_default = detect_tool("ffmpeg")
        self.ffprobe_default = detect_tool("ffprobe")

    def run(self):
        # 捕获整个 run 的异常，防止线程未处理异常导致不可预期行为
        try:
            while not self.stop_event.is_set():
                try:
                    src = self.task_queue.get_nowait()
                except Exception as e:
                    # 更明确地捕获队列为空的情况
                    if "queue" in str(type(e)).lower() or isinstance(e, Queue.Empty):
                        break  # 队列为空，则结束循环
                    else:
                        raise e  # 其他异常仍然抛出
                try:
                    self._process_file(src)
                except Exception as e:
                    # 标记该文件为 error，但继续处理队列中的其他文件
                    self.db.update_file_status(src, 'error', error=str(e))
                    self.status_signal.emit(src, 'error')
                    self.log_signal.emit(f"[异常] 任务处理异常: {e}")
                finally:
                    try:
                        self.task_queue.task_done()
                    except:
                        pass
        except Exception as e:
            self.log_signal.emit(f"[异常] Worker 主循环异常: {e}")
            # 添加详细的错误信息
            import traceback
            self.log_signal.emit(f"[Traceback] {traceback.format_exc()}")
        finally:
            self.log_signal.emit("工作线程退出")

    def _process_file(self, src):
        src_p = Path(src)
        input_dir = Path(self.settings.get('input_dir', '.'))
        out_dir = Path(self.settings['output_dir'])
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            rel = src_p.relative_to(input_dir)
        except Exception:
            rel = src_p.name
        out_path = out_dir / rel
        out_path = out_path.with_suffix('.mp4')
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if self.settings.get('skip_existing') and out_path.exists():
            self.db.update_file_status(src, 'done', output=str(out_path))
            self.status_signal.emit(src, 'done')
            self.log_signal.emit(f"跳过已存在: {src}")
            return

        # ffmpeg path selection (user-specified > detected default)
        ffmpeg_user = (self.settings.get('ffmpeg_path') or '').strip()
        ffmpeg_path = ffmpeg_user or self.ffmpeg_default or 'ffmpeg'
        ffmpeg_p = Path(ffmpeg_path)
        if ffmpeg_p.is_dir():
            ffmpeg_p = ffmpeg_p / 'ffmpeg.exe'
        if ffmpeg_p.exists():
            ffmpeg_exec = str(ffmpeg_p)
        else:
            ffmpeg_exec = ffmpeg_path  # let system resolve, might fail later

        codec = self.settings.get('video_codec', 'libx264')
        crf = str(self.settings.get('crf', 23))
        preset = self.settings.get('preset', 'medium')
        audio_bitrate = self.settings.get('audio_bitrate', '128k')
        threads = int(self.settings.get('threads', 0) or 0)
        scale = self.settings.get('scale', '') or ''
        fps = self.settings.get('fps', '') or ''

        total_sec = probe_duration(self.ffprobe_default, str(src_p)) if self.ffprobe_default else 0.0
        if total_sec is None:
            total_sec = 0.0

        cmd = [ffmpeg_exec, '-y', '-i', str(src_p)]
        if scale:
            cmd += ['-vf', f"scale={scale}"]
        if fps:
            cmd += ['-r', fps]

        if codec.startswith('lib') or codec.startswith('libaom') or codec.startswith('libsvt'):
            cmd += ['-c:v', codec, '-preset', preset, '-crf', crf]
        elif codec.endswith('_nvenc'):
            preset_nvenc = preset if preset in NVENC_PRESETS else 'default'
            cmd += ['-c:v', codec, '-preset', preset_nvenc, '-cq', crf]
        else:
            cmd += ['-c:v', codec]

        cmd += ['-c:a', 'aac', '-b:a', audio_bitrate]
        if threads > 0:
            cmd += ['-threads', str(threads)]

        # use -progress pipe:1 for real-time progress
        cmd += ['-progress', 'pipe:1', '-nostats', str(out_path)]

        self.db.update_file_status(src, 'processing', output=str(out_path))
        self.status_signal.emit(src, 'processing')
        self.log_signal.emit(f"开始压缩: {src}")
        self.log_signal.emit(f"命令: {' '.join(cmd)}")

        # Windows hide console
        creationflags = 0
        startupinfo = None
        if os.name == 'nt':
            creationflags = subprocess.CREATE_NO_WINDOW
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            except Exception:
                startupinfo = None

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding='utf-8',
                errors='ignore',
                creationflags=creationflags,
                startupinfo=startupinfo
            )
        except Exception as e:
            self.db.update_file_status(src, 'error', error=str(e))
            self.status_signal.emit(src, 'error')
            self.log_signal.emit(f"[异常] 启动 ffmpeg 失败: {e}")
            return

        cur_seconds = 0.0
        percent = 0

        try:
            for raw in proc.stdout:
                if self.stop_event.is_set():
                    try:
                        proc.terminate()
                    except:
                        pass
                    break
                line = raw.strip()
                if not line:
                    continue
                if 'error' in line.lower() or '错误' in line or 'exception' in line.lower():
                    self.log_signal.emit(f"[错误] {line}")
                else:
                    self.log_signal.emit(line)

                m_ms = PROGRESS_OUT_TIME_MS.search(line)
                if m_ms:
                    cur_seconds = int(m_ms.group(1)) / 1000.0
                else:
                    m_ot = PROGRESS_OUT_TIME.search(line)
                    if m_ot:
                        cur_seconds = time_str_to_seconds(m_ot.group(1))

                if total_sec and total_sec > 0:
                    new_percent = int(min(100, (cur_seconds / total_sec) * 100))
                else:
                    new_percent = int(min(99, percent + 1))

                if new_percent != percent:
                    percent = new_percent
                    self.progress_signal.emit(src, percent, cur_seconds, total_sec)
            ret = proc.wait()
            if ret == 0:
                self.progress_signal.emit(src, 100, total_sec, total_sec)
                self.db.update_file_status(src, 'done', output=str(out_path))
                self.status_signal.emit(src, 'done')
                self.log_signal.emit(f"完成: {src} -> {out_path}")
            else:
                self.db.update_file_status(src, 'error', output=str(out_path), returncode=ret)
                self.status_signal.emit(src, 'error')
                self.log_signal.emit(f"[错误] ffmpeg 返回码 {ret}")
        except Exception as e:
            try:
                proc.terminate()
            except:
                pass
            self.db.update_file_status(src, 'error', error=str(e))
            self.status_signal.emit(src, 'error')
            self.log_signal.emit(f"[异常] 处理 ffmpeg 输出失败: {e}")
            import traceback
            self.log_signal.emit(f"[Traceback] {traceback.format_exc()}")

# ---- GUI ----

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('视频批量压缩器')
        self.resize(1100, 720)

        self.db = ProgressDBLocal(Path(DEFAULT_PROGRESS))
        self.stop_event = threading.Event()
        self.task_queue = Queue()
        self.worker_thread = None
        self.worker = None

        # detect tools (compatible with PyInstaller)
        self.detected_ffmpeg = detect_tool("ffmpeg")
        self.detected_ffprobe = detect_tool("ffprobe")

        self._build_ui()
        self._connect_signals()
        self.load_settings()
        self.refresh_file_table()
        # if ffmpeg/ffprobe missing, warn & disable start
        self._check_tools_on_startup()

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        v = QtWidgets.QVBoxLayout(central)

        top = QtWidgets.QHBoxLayout(); v.addLayout(top)
        self.input_dir_edit = QtWidgets.QLineEdit()
        self.input_dir_btn = QtWidgets.QPushButton('选择输入目录')
        self.output_dir_edit = QtWidgets.QLineEdit()
        self.output_dir_btn = QtWidgets.QPushButton('选择输出目录')
        top.addWidget(QtWidgets.QLabel('输入:')); top.addWidget(self.input_dir_edit); top.addWidget(self.input_dir_btn)
        top.addWidget(QtWidgets.QLabel('输出:')); top.addWidget(self.output_dir_edit); top.addWidget(self.output_dir_btn)

        params1 = QtWidgets.QHBoxLayout(); v.addLayout(params1)
        self.codec_combo = QtWidgets.QComboBox(); self.codec_combo.addItems([
            'libx264', 'libx265', 'libaom-av1', 'libsvtav1',
            'h264_nvenc', 'hevc_nvenc', 'av1_nvenc'
        ])
        self.crf_spin = QtWidgets.QSpinBox(); self.crf_spin.setRange(0, 51); self.crf_spin.setValue(23)
        self.preset_combo = QtWidgets.QComboBox(); self.preset_combo.addItems(CPU_PRESETS)
        self.audio_bitrate_edit = QtWidgets.QLineEdit('128k')
        self.threads_spin = QtWidgets.QSpinBox(); self.threads_spin.setRange(0, 64); self.threads_spin.setValue(0)
        self.scale_edit = QtWidgets.QLineEdit('')
        self.fps_edit = QtWidgets.QLineEdit('')
        self.skip_existing_chk = QtWidgets.QCheckBox('跳过已存在输出')

        params1.addWidget(QtWidgets.QLabel('视频编码')); params1.addWidget(self.codec_combo)
        params1.addWidget(QtWidgets.QLabel('CRF/CQ')); params1.addWidget(self.crf_spin)
        params1.addWidget(QtWidgets.QLabel('preset')); params1.addWidget(self.preset_combo)
        params1.addWidget(QtWidgets.QLabel('音频比特率')); params1.addWidget(self.audio_bitrate_edit)
        params1.addWidget(QtWidgets.QLabel('线程(0=auto)')); params1.addWidget(self.threads_spin)
        params1.addWidget(self.skip_existing_chk)

        params2 = QtWidgets.QHBoxLayout(); v.addLayout(params2)
        params2.addWidget(QtWidgets.QLabel('scale (如1280:-2)')); params2.addWidget(self.scale_edit)
        params2.addWidget(QtWidgets.QLabel('FPS')); params2.addWidget(self.fps_edit)
        self.ffmpeg_path_edit = QtWidgets.QLineEdit(self.detected_ffmpeg or '')
        params2.addWidget(QtWidgets.QLabel('ffmpeg 路径')); params2.addWidget(self.ffmpeg_path_edit)
        self.ffprobe_label = QtWidgets.QLabel(f"ffprobe: {self.detected_ffprobe or '未找到'}")
        params2.addWidget(self.ffprobe_label)

        btns = QtWidgets.QHBoxLayout(); v.addLayout(btns)
        self.scan_btn = QtWidgets.QPushButton('扫描任务')
        self.start_btn = QtWidgets.QPushButton('开始')
        self.stop_btn = QtWidgets.QPushButton('停止')
        self.open_log_btn = QtWidgets.QPushButton('打开日志')
        btns.addWidget(self.scan_btn); btns.addWidget(self.start_btn); btns.addWidget(self.stop_btn); btns.addWidget(self.open_log_btn)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical); v.addWidget(splitter)
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['文件', '状态', '输出', '最后更新时间', '进度', '时间'])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        splitter.addWidget(self.table)

        self.log_text = QtWidgets.QTextEdit(); self.log_text.setReadOnly(True)
        splitter.addWidget(self.log_text)

        self.progressbars = {}

    def _connect_signals(self):
        self.input_dir_btn.clicked.connect(self.choose_input_dir)
        self.output_dir_btn.clicked.connect(self.choose_output_dir)
        self.scan_btn.clicked.connect(self.scan_and_sync)
        self.start_btn.clicked.connect(self.start_worker)
        self.stop_btn.clicked.connect(self.stop_worker)
        self.open_log_btn.clicked.connect(self.open_app_log)
        self.codec_combo.currentTextChanged.connect(self.update_presets)

    def update_presets(self, codec_name):
        self.preset_combo.clear()
        if codec_name.endswith('_nvenc'):
            self.preset_combo.addItems(NVENC_PRESETS)
        else:
            self.preset_combo.addItems(CPU_PRESETS)

    def choose_input_dir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, '选择输入目录')
        if d: self.input_dir_edit.setText(d)

    def choose_output_dir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, '选择输出目录')
        if d: self.output_dir_edit.setText(d)

    def log(self, text: str):
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = f"[{ts}] {text}"
        cursor = self.log_text.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        fmt = QtGui.QTextCharFormat()
        if "[错误]" in text or "[异常]" in text or "Error" in text:
            fmt.setForeground(QtGui.QBrush(QtCore.Qt.red))
        elif "完成" in text or "完成:" in text:
            fmt.setForeground(QtGui.QBrush(QtGui.QColor(0, 128, 0)))
        else:
            fmt.setForeground(QtGui.QBrush(QtCore.Qt.black))
        cursor.insertText(line + "\n", fmt)
        try:
            with open(DEFAULT_APP_LOG, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except:
            pass

    def scan_and_sync(self):
        input_dir = self.input_dir_edit.text().strip()
        if not input_dir:
            QtWidgets.QMessageBox.warning(self, '提示', '请先选择输入目录')
            return
        d = Path(input_dir)
        if not d.exists():
            QtWidgets.QMessageBox.warning(self, '提示', '输入目录不存在')
            return
        added = 0
        for p in d.rglob('*'):
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
                key = str(p.resolve())
                if key not in self.db.data['files']:
                    self.db.add_file(key)
                    added += 1
        self.log(f"扫描完成，新增 {added} 个任务")
        self.refresh_file_table()

    def refresh_file_table(self):
        files = list(self.db.all().items())
        self.table.setRowCount(len(files))
        self.progressbars.clear()
        for i, (src, info) in enumerate(files):
            status = info.get('status', '')
            out = info.get('output', '')
            lu = info.get('last_update', info.get('added', ''))
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(src))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(status))
            self.table.setItem(i, 2, QtWidgets.QTableWidgetItem(out))
            self.table.setItem(i, 3, QtWidgets.QTableWidgetItem(lu))
            pb = QtWidgets.QProgressBar()
            pb.setRange(0, 100)
            pb.setValue(0)
            self.table.setCellWidget(i, 4, pb)
            self.progressbars[src] = pb
            self.table.setItem(i, 5, QtWidgets.QTableWidgetItem(''))
            self._apply_row_color(i, status)

    def _apply_row_color(self, row: int, status: str):
        if status == 'error':
            color = QtGui.QColor(255, 200, 200)
        elif status == 'done':
            color = QtGui.QColor(200, 255, 200)
        else:
            color = QtGui.QColor(255, 255, 255)
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item is None:
                item = QtWidgets.QTableWidgetItem('')
                self.table.setItem(row, col, item)
            item.setBackground(color)

    def gather_settings(self):
        return {
            'input_dir': self.input_dir_edit.text().strip(),
            'output_dir': self.output_dir_edit.text().strip(),
            'ffmpeg_path': self.ffmpeg_path_edit.text().strip(),
            'video_codec': self.codec_combo.currentText(),
            'crf': self.crf_spin.value(),
            'preset': self.preset_combo.currentText(),
            'audio_bitrate': self.audio_bitrate_edit.text().strip(),
            'threads': self.threads_spin.value(),
            'scale': self.scale_edit.text().strip(),
            'fps': self.fps_edit.text().strip(),
            'skip_existing': self.skip_existing_chk.isChecked(),
        }

    def start_worker(self):
        settings = self.gather_settings()
        if not settings['input_dir'] or not settings['output_dir']:
            QtWidgets.QMessageBox.warning(self, '提示', '请先设置输入和输出目录')
            return
        # check ffmpeg supports codec
        ffmpeg_exec = settings['ffmpeg_path'] or self.detected_ffmpeg
        ffmpeg_p = Path(ffmpeg_exec)
        if ffmpeg_p.is_dir():
            ffmpeg_p = ffmpeg_p / 'ffmpeg.exe'
        ffmpeg_exec_check = str(ffmpeg_p) if ffmpeg_p.exists() else ffmpeg_exec
        if not ffmpeg_supports_codec(ffmpeg_exec_check, settings['video_codec']):
            QtWidgets.QMessageBox.warning(self, '错误', f"ffmpeg 不支持编码器: {settings['video_codec']}")
            return

        for src, info in list(self.db.all().items()):
            if info.get('status') in ('processing',):
                self.db.update_file_status(src, 'pending')
        self.task_queue = Queue()
        for src, info in self.db.all().items():
            if info.get('status') == 'pending':
                self.task_queue.put(src)
        if self.task_queue.empty():
            QtWidgets.QMessageBox.information(self, '信息', '没有待处理文件（请先扫描）')
            return
        self.stop_event.clear()
        self.worker = CompressorWorker(self.task_queue, self.db, settings, self.stop_event)
        self.worker.progress_signal.connect(self.on_progress_update)
        self.worker.status_signal.connect(self.on_status_update)
        self.worker.log_signal.connect(self.on_log)
        self.worker_thread = threading.Thread(target=self.worker.run, daemon=True)
        self.worker_thread.start()
        self.log("工作线程已启动")
        QtCore.QTimer.singleShot(500, self.refresh_file_table)

    def stop_worker(self):
        self.stop_event.set()
        self.log("发送停止信号")

    def on_progress_update(self, src: str, percent: int, cur_sec: float, total_sec: float):
        # 使用 QMetaObject.invokeMethod 确保在主线程中更新GUI
        def update_gui():
            pb = self.progressbars.get(src)
            if pb:
                pb.setValue(percent)
            for i in range(self.table.rowCount()):
                if self.table.item(i, 0) and self.table.item(i, 0).text() == src:
                    time_text = f"{seconds_to_time_str(cur_sec)} / {seconds_to_time_str(total_sec)}" if total_sec and total_sec > 0 else f"{seconds_to_time_str(cur_sec)} / --:--:--"
                    self.table.setItem(i, 5, QtWidgets.QTableWidgetItem(time_text))
                    break
        
        # 确保在主线程中执行GUI更新
        QtCore.QMetaObject.invokeMethod(self, "update_gui", QtCore.Qt.QueuedConnection, 
                                       QtCore.Q_ARG(str, src), QtCore.Q_ARG(int, percent), 
                                       QtCore.Q_ARG(float, cur_sec), QtCore.Q_ARG(float, total_sec))
    
    @QtCore.pyqtSlot(str, int, float, float)
    def update_gui(self, src, percent, cur_sec, total_sec):
        pb = self.progressbars.get(src)
        if pb:
            pb.setValue(percent)
        for i in range(self.table.rowCount()):
            if self.table.item(i, 0) and self.table.item(i, 0).text() == src:
                time_text = f"{seconds_to_time_str(cur_sec)} / {seconds_to_time_str(total_sec)}" if total_sec and total_sec > 0 else f"{seconds_to_time_str(cur_sec)} / --:--:--"
                self.table.setItem(i, 5, QtWidgets.QTableWidgetItem(time_text))
                break

    def on_status_update(self, src: str, status: str):
        self.db.update_file_status(src, status)
        for i in range(self.table.rowCount()):
            if self.table.item(i, 0) and self.table.item(i, 0).text() == src:
                self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(status))
                self._apply_row_color(i, status)
                break

    def on_log(self, text: str):
        self.log(text)

    def open_app_log(self):
        p = Path(DEFAULT_APP_LOG)
        if p.exists():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(p.resolve())))
        else:
            QtWidgets.QMessageBox.information(self, '信息', '日志文件不存在')

    def load_settings(self):
        try:
            with open('settings.json', 'r', encoding='utf-8') as f:
                s = json.load(f)
            self.input_dir_edit.setText(s.get('input_dir', ''))
            self.output_dir_edit.setText(s.get('output_dir', ''))
            self.ffmpeg_path_edit.setText(s.get('ffmpeg_path', self.detected_ffmpeg or ''))
            self.codec_combo.setCurrentText(s.get('video_codec', 'libx264'))
            self.crf_spin.setValue(int(s.get('crf', 23)))
            self.update_presets(s.get('video_codec', 'libx264'))
            self.preset_combo.setCurrentText(s.get('preset', 'medium'))
            self.audio_bitrate_edit.setText(s.get('audio_bitrate', '128k'))
            self.threads_spin.setValue(int(s.get('threads', 0)))
            self.scale_edit.setText(s.get('scale', ''))
            self.fps_edit.setText(s.get('fps', ''))
            self.skip_existing_chk.setChecked(s.get('skip_existing', False))
        except Exception:
            pass

    def closeEvent(self, event):
        s = self.gather_settings()
        try:
            with open('settings.json', 'w', encoding='utf-8') as f:
                json.dump(s, f, ensure_ascii=False, indent=2)
        except:
            pass
        try:
            self.stop_event.set()
            if self.worker_thread and self.worker_thread.is_alive():
                # 增加超时时间，确保线程安全退出
                self.worker_thread.join(timeout=3)
        except Exception as e:
            print(f"关闭线程时出错: {e}")
        
        event.accept()

    def _check_tools_on_startup(self):
        # check ffmpeg and ffprobe and update UI / enable start button accordingly
        ffmpeg_found = detect_tool("ffmpeg")
        ffprobe_found = detect_tool("ffprobe")
        self.ffprobe_label.setText(f"ffprobe: {ffprobe_found or '未找到'}")
        if not ffmpeg_found:
            self.log("[错误] 未检测到 ffmpeg，请将 ffmpeg.exe 放在程序目录或安装到系统 PATH，或在界面填写路径")
            self.start_btn.setEnabled(False)
            QtWidgets.QMessageBox.warning(self, "缺少依赖", "未检测到 ffmpeg，可在界面填写 ffmpeg 路径或把 ffmpeg.exe 放到程序目录后重启程序。开始按钮已禁用。")
        else:
            self.log(f"检测到 ffmpeg: {ffmpeg_found}")
        if not ffprobe_found:
            self.log("[警告] 未检测到 ffprobe，进度百分比可能不精确（建议打包或放置 ffprobe.exe）")
            # 不强制禁用 start，仅警告

# ---- main ----

def main():
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
