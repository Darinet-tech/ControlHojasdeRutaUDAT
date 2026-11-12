@echo off
REM Copia de seguridad diaria de la base de datos en backups\ (ver README). Se programa a las 21:30.
cd /d "%~dp0"
if not exist logs mkdir logs
echo ==== %date% %time% ==== >> logs\respaldo.log
".venv\Scripts\python.exe" manage.py respaldar_base >> logs\respaldo.log 2>&1
