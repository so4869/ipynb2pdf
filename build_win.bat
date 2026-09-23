@echo off
REM ipynb2pdf Windows build script  ->  dist\ipynb2pdf.exe
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist .venv (
  %PY% -m venv .venv || goto :err
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller || goto :err
python tools\make_fontlist.py || goto :err
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
pyinstaller --clean --noconfirm ipynb2pdf.spec || goto :err
echo.
echo ===== 빌드 완료: dist\ipynb2pdf.exe =====
echo 테스트: dist\ipynb2pdf.exe tests\sample.ipynb
exit /b 0
:err
echo 빌드 실패
exit /b 1
