@echo off
setlocal
cd /d "%~dp0"
title Building FAAR Manager.exe

set "PY="
py -3 --version 1>NUL 2>&1 && set "PY=py -3"
if not defined PY (
  python --version 1>NUL 2>&1 && set "PY=python"
)
if not defined PY (
  echo Python wasn't found. Install it from python.org and tick "Add python.exe to PATH".
  pause
  exit /b 1
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
if exist build_tess rmdir /s /q build_tess
mkdir build_tess
copy /y "%TESS%\tesseract.exe" build_tess\ >NUL
copy /y "%TESS%\*.dll" build_tess\ >NUL
if exist "%TESS%\LICENSE" copy /y "%TESS%\LICENSE" build_tess\TESSERACT_LICENSE.txt >NUL
if exist "%TESS%\COPYING" copy /y "%TESS%\COPYING" build_tess\TESSERACT_COPYING.txt >NUL

echo.
echo Building, this takes a few minutes...
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name "FAAR Manager" ^
  --collect-data customtkinter ^
  --add-data "tessdata;tessdata" ^
  --add-data "assets;assets" ^
  --add-data "build_tess;tesseract" ^
  --icon "assets\icon.ico" ^
  main.py
if errorlevel 1 (
  echo.
  echo The build failed. Scroll up for the error.
  pause
  exit /b 1
)

if exist data (
  echo.
  echo Copying your accounts and settings next to the new exe...
  xcopy /e /i /y data "dist\data" >NUL
)

echo.
echo Done: dist\FAAR Manager.exe
echo Tesseract is inside it, so people only need this one file.
echo That single file is what you upload as a release. It makes its own "data" folder
echo next to itself the first time it runs (the copied one above is only for you).
explorer dist
pause
