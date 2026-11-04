@echo off
chcp 65001 >nul
if not exist "%~dp0python\python.exe" goto notextracted
"%~dp0python\python.exe" -I "%~dp0app\lotro_tr.py" install %*
exit /b %errorlevel%

:notextracted
echo.
echo Önce ZIP dosyasını bir klasöre çıkarın: ZIP dosyasına sağ tıklayıp "Tümünü ayıkla" deyin.
echo Sonra çıkan klasördeki Kur.cmd dosyasını çalıştırın.
echo.
echo Extract the ZIP first (right click, Extract All), then run Kur.cmd from the extracted folder.
echo.
pause
exit /b 1
