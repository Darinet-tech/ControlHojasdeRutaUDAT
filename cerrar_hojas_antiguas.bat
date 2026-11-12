@echo off
REM Cierra las hojas de ruta que siguen abiertas pasadas las 21:00 (y las de dias anteriores). Se programa cada dia a las 21:00 (ver README).
cd /d "%~dp0"
if not exist logs mkdir logs
echo ==== %date% %time% ==== >> logs\cerrar_hojas.log
".venv\Scripts\python.exe" manage.py cerrar_hojas_antiguas >> logs\cerrar_hojas.log 2>&1
