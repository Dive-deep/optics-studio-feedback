@echo off
setlocal
rem Uses the user's Python; no virtual environment or automatic installation.
pushd "%~dp0"
if errorlevel 1 goto directory_error
if defined OPTICS_PYTHON goto custom_python
where py >nul 2>&1
if errorlevel 1 goto default_python
py -3.12 -X utf8 "%~dp0launch.py" %*
goto finished
:custom_python
"%OPTICS_PYTHON%" -X utf8 "%~dp0launch.py" %*
goto finished
:default_python
where python >nul 2>&1
if errorlevel 1 goto missing_python
python -X utf8 "%~dp0launch.py" %*
goto finished
:missing_python
echo Python 3.12 x64 was not found. Install it, then run:
echo py -3.12 -m pip install -r requirements.txt
set "OPTICS_EXIT=2"
goto report_failure
:finished
set "OPTICS_EXIT=%ERRORLEVEL%"
if not "%OPTICS_EXIT%"=="0" goto report_failure
popd
exit /b 0
:report_failure
echo.
echo The application could not complete. Review the error above.
pause
popd
exit /b %OPTICS_EXIT%
:directory_error
echo Cannot open the release directory. Extract the ZIP to a local folder first.
pause
exit /b 2
