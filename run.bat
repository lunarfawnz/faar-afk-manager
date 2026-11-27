@echo off
title FAAR Manager
cd /d "%~dp0"

set "PY="
py -3 --version 1>NUL 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  python --version 1>NUL 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo Couldn't start Python with "py" or "python".
  echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  pause
  exit /b
)
echo Using %PY%

if not exist data mkdir data
%PY% -c "import re, importlib.metadata as m; [m.version(re.split(r'[<>=!~;\[ ]', l.strip())[0]) for l in open('requirements.txt') if l.strip() and not l.startswith('#')]; import customtkinter, cv2, numpy, PIL, requests, psutil, pytesseract, cryptography" 1>NUL 2>&1
if not errorlevel 1 goto deps_ok
echo Installing what the app needs...
%PY% -m pip install --upgrade --timeout 30 -r requirements.txt
if not errorlevel 1 goto deps_ok
echo Normal download failed. Trying a mirror...
%PY% -m pip install --upgrade --timeout 30 -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
if not errorlevel 1 goto deps_ok
echo.
echo Install failed. Send a screenshot of the error above.
pause
exit /b
:deps_ok
set "PYW="
if "%PY%"=="py -3" (
  pyw -3 --version 1>NUL 2>&1
  if not errorlevel 1 set "PYW=pyw -3"
)
if not defined PYW (
  pythonw --version 1>NUL 2>&1
  if not errorlevel 1 set "PYW=pythonw"
)
if not defined PYW (
  %PY% main.py
  if errorlevel 1 pause
  exit /b
)
start "" %PYW% main.py
exit /b
