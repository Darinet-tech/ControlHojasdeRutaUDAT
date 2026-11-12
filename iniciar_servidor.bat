@echo off
REM Inicia la aplicacion para los usuarios (ver DESPLIEGUE.md). Deje esta ventana abierta o instalela como servicio/tarea de inicio.
cd /d "%~dp0"
if not exist logs mkdir logs
".venv\Scripts\python.exe" servir.py >> logs\servidor.log 2>&1
