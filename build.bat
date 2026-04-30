@echo off
REM Builds dist\TextRecog\TextRecog.exe using PyInstaller --onedir.
REM PaddlePaddle ships ~200 MB of native DLLs that --onefile can't reliably bundle.

setlocal
set "CONDA=E:\Dev\Envs\Conda\Scripts\conda.exe"
pushd "%~dp0"

REM Kill any running instance so dist can be deleted (file locks otherwise
REM cause PyInstaller's COLLECT step to fail with "output directory not empty").
taskkill /f /im TextRecog.exe >nul 2>&1

if exist build  rmdir /s /q build
if exist dist   rmdir /s /q dist
if exist dist (
    echo ERROR: failed to remove dist\ - is TextRecog.exe still running, or a file open?
    exit /b 1
)

"%CONDA%" run -n textrecog --no-capture-output --live-stream pyinstaller build.spec
if errorlevel 1 (
    echo.
    echo Build failed. See output above.
    popd
    exit /b 1
)

echo.
echo Build complete. Run: dist\TextRecog\TextRecog.exe
popd
