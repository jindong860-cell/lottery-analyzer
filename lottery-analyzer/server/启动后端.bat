@echo off
rem 彩票分析助手 - 一键启动后端（Windows）
rem 自动选择可用 Python：已有 .venv 优先；其次 DSH 内置运行时（numpy/Pillow 已预装，零安装零联网）；
rem 最后用系统 python 建虚拟环境并装依赖。
chcp 65001 >nul
cd /d "%~dp0"

set "DSH_PY=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
set "PYEXE="

if exist .venv\Scripts\python.exe (
  set "PYEXE=.venv\Scripts\python.exe"
  echo [环境] 使用已有虚拟环境 .venv
) else if exist "%DSH_PY%" (
  set "PYEXE=%DSH_PY%"
  echo [环境] 使用内置 Python 运行时（依赖已预装，无需安装）
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [错误] 未找到可用 Python，请先安装 Python 3.10+ 并加入 PATH。
    pause
    exit /b 1
  )
  echo [环境] 使用系统 Python，首次运行创建虚拟环境并安装依赖（需联网）...
  python -m venv .venv
  if errorlevel 1 goto :fail
  set "PYEXE=.venv\Scripts\python.exe"
  "%PYEXE%" -m pip install -r requirements.txt
  if errorlevel 1 goto :fail
)

echo [启动] 后端启动中，3 秒后自动打开网页 http://127.0.0.1:8000/ ...
echo [提示] 本窗口保持开启即服务在线；关闭窗口即停止服务。
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000/"
"%PYEXE%" run_server.py
goto :eof

:fail
echo.
echo [失败] 初始化未完成，请把上方错误信息反馈给开发者。
pause
