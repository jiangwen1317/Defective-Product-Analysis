@echo off
rem 提交前检查入口：hooksPath 自检 + ruff 静态检查 + 三个子项目 pytest 套件
rem 用法：在仓库根执行 check.bat；任一环节失败即以非零码退出
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"

echo [自检] git core.hooksPath 是否指向 githooks ...
set "HOOKS_PATH="
for /f "usebackq delims=" %%H in (`git config core.hooksPath 2^>nul`) do set "HOOKS_PATH=%%H"
if /i not "%HOOKS_PATH%"=="githooks" (
    echo.
    echo [hooksPath 自检失败] 当前 core.hooksPath="%HOOKS_PATH%"，提交前门禁未启用。
    echo 请在仓库根执行以下命令启用后重试：
    echo.
    echo     git config core.hooksPath githooks
    echo.
    goto :fail
)

echo [1/5] ruff 静态检查（AGENTS.md 机械化规则）...
"%PY%" -m ruff check . || goto :fail

echo [2/5] 存量基线豁免只减不增断言 ...
"%PY%" tools\check_exemption_baseline.py || goto :fail

echo [3/5] pytest: upper computer ...
"%PY%" -m pytest "upper computer" -q || goto :fail

echo [4/5] pytest: database-analysis ...
"%PY%" -m pytest "database-analysis\tests" -q || goto :fail

echo [5/5] pytest: Log-Download ...
"%PY%" -m pytest "Log-Download" -q || goto :fail

echo.
echo 全部检查通过。
exit /b 0

:fail
echo.
echo 检查未通过，禁止提交。
exit /b 1
