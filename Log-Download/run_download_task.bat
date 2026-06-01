@echo off
REM LVTS 日志下载器 - Windows 任务计划程序执行脚本
REM 
REM 使用方法:
REM 1. 打开 Windows 任务计划程序
REM 2. 创建基本任务
REM 3. 设置触发器 (如每天特定时间、每小时等)
REM 4. 操作选择"启动程序",浏览选择此脚本
REM 5. 完成创建

REM 切换到脚本所在目录
cd /d "%~dp0"

REM 设置 Python 虚拟环境路径 (如果使用虚拟环境)
REM set PYTHON_PATH=.venv\Scripts\python.exe
REM 或使用系统 Python
set PYTHON_PATH=python

REM 执行下载器 (单次执行模式)
%PYTHON_PATH% log_downloader.py --once --config config.json

REM 检查执行结果
if %ERRORLEVEL% EQU 0 (
    echo 执行成功
) else (
    echo 执行失败,错误代码: %ERRORLEVEL%
)

REM 保持窗口打开 (调试用,可删除)
REM pause