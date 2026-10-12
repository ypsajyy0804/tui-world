@echo off
setlocal
cd /d %~dp0
set "PIP_CACHE_DIR=%~dp0.pipcache"
set "TEMP=%~dp0.tmp"
set "TMP=%~dp0.tmp"
if not exist ".tmp" mkdir ".tmp"
if not exist ".venv\Scripts\python.exe" (
  echo [setup] 首次运行：在 D 盘创建虚拟环境并安装依赖...
  py -3.13 -m venv .venv 2>nul || py -3 -m venv .venv 2>nul || python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
)
".venv\Scripts\python.exe" -m core.app --open %*
