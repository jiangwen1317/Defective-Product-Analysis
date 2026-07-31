@echo off
rem 克隆后一键初始化入口：venv 创建 + 依赖安装 + hooksPath 门禁启用 + check.bat 验证
rem 用法：在仓库根执行 setup.bat；步骤与 README「克隆后初始化」1-5 一一对应，可重复执行（幂等）
rem 任一环节失败即以非零码退出；本脚本不增删或跳过 check.bat 的检查环节
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"

echo [1/5] 创建虚拟环境 .venv（要求 Python ^>= 3.10）...
if exist "%PY%" (
    echo 已存在 .venv，跳过创建。
) else (
    python -m venv .venv || goto :fail
)

echo [2/5] 安装仓库级开发/检查依赖 requirements-dev.txt ...
"%PY%" -m pip install -r requirements-dev.txt || goto :fail

echo [3/5] 安装三个子项目的运行依赖 ...
"%PY%" -m pip install -r "upper computer\requirements.txt" || goto :fail
"%PY%" -m pip install -r database-analysis\requirements.txt || goto :fail
"%PY%" -m pip install -r Log-Download\requirements.txt || goto :fail

echo [4/5] 启用提交前门禁 git config core.hooksPath githooks ...
git config core.hooksPath githooks || goto :fail

echo [5/5] 运行检查入口 check.bat 验证环境 ...
call check.bat || goto :fail

echo.
echo 初始化完成，提交前门禁已启用。
exit /b 0

:fail
echo.
echo 初始化未完成，请根据上方输出修复后重新执行 setup.bat。
exit /b 1
