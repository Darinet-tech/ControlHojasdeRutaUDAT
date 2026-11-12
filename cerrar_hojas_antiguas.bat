@echo off
REM Cierra las hojas de ruta de dias anteriores que quedaron abiertas. Se programa cada noche a las 00:05 (ver README).
cd /d "%~dp0"
if not exist logs mkdir logs
echo ==== %date% %time% ==== >> logs\cerrar_hojas.log
".venv\Scripts\python.exe" manage.py cerrar_hojas_antiguas >> logs\cerrar_hojas.log 2>&1
