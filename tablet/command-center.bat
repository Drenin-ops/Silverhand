@echo off
REM ============================================================
REM  SILVERHAND -- Network Command Center launcher (Windows)
REM  Double-click on the tablet to open the monitor dashboard.
REM  Edit HOST / PORT below if your Main PC's IP is different.
REM ============================================================

setlocal
set "HOST=10.0.0.131"
set "PORT=7477"
set "URL=http://%HOST%:%PORT%/monitor"

echo.
echo   SILVERHAND // connecting to command center
echo   %URL%
echo.

REM --- Preferred: borderless "app window" (nicer on a dedicated monitor tablet).
REM     Tries Edge, then Chrome, then falls back to the default browser.
set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
set "CHROME_X86=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"

if exist "%EDGE%"      ( start "" "%EDGE%"      --app=%URL% & goto :done )
if exist "%CHROME%"    ( start "" "%CHROME%"    --app=%URL% & goto :done )
if exist "%CHROME_X86%" ( start "" "%CHROME_X86%" --app=%URL% & goto :done )

REM --- Fallback: whatever the default browser is.
start "" "%URL%"

:done
REM  Want true fullscreen kiosk mode? Replace --app=%URL% above with
REM  --kiosk %URL%  (press Alt+F4 or Ctrl+W to exit kiosk).
endlocal
