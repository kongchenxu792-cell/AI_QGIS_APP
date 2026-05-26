@echo off
cd /d "%~dp0"

pushd "%~dp0qgis-portable\bin"
call o4w_env.bat
popd

path %OSGEO4W_ROOT%\apps\qgis-ltr\bin;%PATH%
set QGIS_PREFIX_PATH=%OSGEO4W_ROOT:\=/%/apps/qgis-ltr
set GDAL_FILENAME_IS_UTF8=YES
REM PROJ 9.x reads PROJ_DATA (set by o4w_env.bat), also set PROJ_LIB for GDAL compat
if not defined PROJ_LIB set PROJ_LIB=%OSGEO4W_ROOT%\share\proj
set VSI_CACHE=TRUE
set VSI_CACHE_SIZE=1000000
set QT_PLUGIN_PATH=%OSGEO4W_ROOT%\apps\qgis-ltr\qtplugins;%OSGEO4W_ROOT%\apps\qt5\plugins
set PYTHONPATH=%OSGEO4W_ROOT%\apps\qgis-ltr\python;%PYTHONPATH%

echo ========================================
echo   AIQGIS v0.4 Portable
echo   QGIS: %OSGEO4W_ROOT%
echo ========================================

python "%~dp0src\main.py"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo   Start failed, exit code: %ERRORLEVEL%
    pause
)