@echo off
setlocal
cd /d "%~dp0"
title Building FAAR Manager.exe

set "PY="
for %%V in (3.13 3.12 3.11) do (
  if not defined PY (
    py -%%V --version 1>NUL 2>&1 && set "PY=py -%%V"
  )
)
if not defined PY (
  py -3 --version 1>NUL 2>&1 && set "PY=py -3"
)
if not defined PY (
  python --version 1>NUL 2>&1 && set "PY=python"
)
if not defined PY (
  echo Python wasn't found. Install Python 3.13 from python.org and tick "Add python.exe to PATH".
  pause
  exit /b 1
)

for /f "delims=" %%P in ('%PY% -c "import sys; print(sys.executable)"') do set "PYEXE=%%P"
for /f "delims=" %%P in ('%PY% -c "import sys; print('%%d.%%d' %% sys.version_info[:2])"') do set "PYVER=%%P"
echo Building with Python %PYVER%  (%PYEXE%)
echo "%PYEXE%" | find /i "WindowsApps" >NUL
if not errorlevel 1 (
  echo.
  echo This Python is the Microsoft Store version. PyInstaller can't package it properly, and the exe
  echo would fail with "Failed to load Python DLL". Install Python 3.13 from python.org
  echo ^(https://www.python.org/downloads/^), then run build_exe.bat again.
  pause
  exit /b 1
)
if "%PYVER%"=="3.14" (
  echo.
  echo Note: Python 3.14 is very new and exes built with it can fail to start. If FAAR Manager.exe shows
  echo "Failed to load Python DLL", install Python 3.13 from python.org and build again ^(this script
  echo uses 3.13 automatically when it's installed^).
  echo.
)

echo Installing what the build needs...
%PY% -m pip install --upgrade -r requirements.txt pyinstaller
if errorlevel 1 (
  %PY% -m pip install --upgrade -r requirements.txt pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
)

echo.
echo Looking for Tesseract to put inside the exe...
set "TESS="
for %%D in ("%ProgramFiles%\Tesseract-OCR" "%ProgramFiles(x86)%\Tesseract-OCR" "%LOCALAPPDATA%\Programs\Tesseract-OCR" "%LOCALAPPDATA%\Tesseract-OCR") do (
  if not defined TESS if exist "%%~D\tesseract.exe" set "TESS=%%~D"
)
if not defined TESS (
  for /f "delims=" %%P in ('where tesseract 2^>NUL') do if not defined TESS set "TESS=%%~dpP"
)
if not defined TESS (
  echo.
  echo Tesseract isn't installed on this PC, so it can't be packed into the exe.
  echo Install it once ^(only you need it, people using your exe won't^):
  echo   https://github.com/UB-Mannheim/tesseract/wiki
  echo or in a terminal:  winget install UB-Mannheim.TesseractOCR
  echo Then run build_exe.bat again.
  pause
  exit /b 1
)
echo Found it in "%TESS%"
set "SRC=%~dp0"
set "OUT=%LOCALAPPDATA%\FAAR Manager\build"
if not exist "%OUT%" mkdir "%OUT%"
if exist "%OUT%\tess" rmdir /s /q "%OUT%\tess"
mkdir "%OUT%\tess"
copy /y "%TESS%\tesseract.exe" "%OUT%\tess\" >NUL
copy /y "%TESS%\*.dll" "%OUT%\tess\" >NUL
if exist "%TESS%\LICENSE" copy /y "%TESS%\LICENSE" "%OUT%\tess\TESSERACT_LICENSE.txt" >NUL
if exist "%TESS%\COPYING" copy /y "%TESS%\COPYING" "%OUT%\tess\TESSERACT_COPYING.txt" >NUL

echo.
echo Building, this takes a few minutes...
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name "FAAR Manager" ^
  --distpath "%OUT%\dist" --workpath "%OUT%\work" --specpath "%OUT%" ^
  --collect-data customtkinter ^
  --add-data "%SRC%tessdata;tessdata" ^
  --add-data "%SRC%assets;assets" ^
  --add-data "%SRC%app\web;app\web" ^
  --add-data "%OUT%\tess;tesseract" ^
  --icon "%SRC%assets\icon.ico" ^
  "%SRC%main.py"
if errorlevel 1 (
  echo.
  echo The build failed. Scroll up for the error.
  pause
  exit /b 1
)


echo.
echo Done: %OUT%\dist\FAAR Manager.exe
echo Tesseract is inside it, so people only need this one file.
echo That single file is what you upload as a release. Accounts and settings are kept
echo in %LOCALAPPDATA%\FAAR Manager, never inside the exe or its folder.
explorer "%OUT%\dist"
pause
