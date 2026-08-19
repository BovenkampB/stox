@echo off
REM ====================================================================
REM  Stoxxx dashboard starter
REM  - Start het lokale dashboard en opent je browser op de lokale naam.
REM  - HOST moet in je hosts-bestand naar 127.0.0.1 wijzen
REM    (C:\Windows\System32\drivers\etc\hosts, bewerken als administrator):
REM        127.0.0.1    stoxx.local
REM
REM  Instellingen (pas gerust aan):
REM    PORT=80    -> bereikbaar als http://stoxx.local  (vereist admin; UAC-prompt)
REM    PORT=8000  -> bereikbaar als http://stoxx.local:8000  (geen admin nodig)
REM ====================================================================
setlocal
set "HOST=stoxx.local"
set "PORT=80"

REM Poorten onder 1024 vereisen beheerdersrechten; zo nodig herstarten als admin.
if %PORT% GEQ 1024 goto run
net session >nul 2>&1
if %errorlevel%==0 goto run
echo Poort %PORT% vereist beheerdersrechten. Opnieuw starten als administrator...
powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b

:run
cd /d "%~dp0"
if "%PORT%"=="80" (set "URL=http://%HOST%") else (set "URL=http://%HOST%:%PORT%")

REM Open de browser 2 seconden later (als de server draait) in de achtergrond.
start "" powershell -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process '%URL%'"

echo.
echo   Stoxxx dashboard draait op %URL%
echo   Sluit dit venster om het dashboard te stoppen.
echo.
python -m stox dashboard --host 127.0.0.1 --port %PORT% --no-browser
endlocal
