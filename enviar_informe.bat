@echo off
REM Envia por correo el informe diario con el corte de la hora actual. Se programa a las 16:00 (ver README).
cd /d "%~dp0"
if not exist logs mkdir logs
echo ==== %date% %time% ==== >> logs\informe_diario.log
".venv\Scripts\python.exe" manage.py enviar_informe_diario >> logs\informe_diario.log 2>&1
