@echo off
REM Dev launcher: starts main.py inside the textrecog conda env, then exits.
REM Use this during development; for shipping, build with `build.bat` and run dist\TextRecog\TextRecog.exe.

setlocal
set "CONDA_ROOT=E:\Dev\Envs\Conda"
set "ENV_DIR=%CONDA_ROOT%\envs\textrecog"
set "PYTHONW=%ENV_DIR%\pythonw.exe"

if not exist "%PYTHONW%" (
    echo ERROR: pythonw.exe not found: %PYTHONW%
    echo Make sure the conda env "textrecog" exists.
    pause
    exit /b 1
)

REM Mirror the important parts of conda activation so native DLLs can load.
set "PATH=%ENV_DIR%;%ENV_DIR%\Library\mingw-w64\bin;%ENV_DIR%\Library\usr\bin;%ENV_DIR%\Library\bin;%ENV_DIR%\Scripts;%CONDA_ROOT%\condabin;%PATH%"

start "" /D "%~dp0" "%PYTHONW%" "%~dp0main.py" %*
exit /b %ERRORLEVEL%
