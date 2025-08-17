@echo off
setlocal enabledelayedexpansion

:: 使用第一个参数作为提交信息；若为空，则用时间戳
set MSG=%*
if "%MSG%"=="" set MSG=Auto commit %date% %time%

echo [1/4] git add .
git add .

echo [2/4] git commit -m "%MSG%"
git commit -m "%MSG%"

echo [3/4] git pull --rebase
git pull --rebase

echo [4/4] git push
git push

echo Done.
pause
