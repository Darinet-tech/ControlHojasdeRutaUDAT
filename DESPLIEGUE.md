# Despliegue de «Mesa de Pruebas» (UDAT) — guía para el grupo de TI

Aplicación web interna: **Django 5.2 + PostgreSQL**. La pantalla (React) ya viene compilada en el paquete: **no hace falta Node.js** en el servidor.
Un solo proceso (`servir.py`) entrega la pantalla, la API y la administración (`/admin`) en **un único puerto** (8000 por defecto).

## 1. Qué necesita el servidor
| Requisito | Detalle |
|---|---|
| Sistema | Windows Server o Linux |
| Python | 3.11 o superior (probado con 3.13) |
| PostgreSQL | 16 o superior, con una base y un usuario propios (ver paso 2) |
| Hora | Zona horaria de Cuba (`America/Havana`). Las horas de corte (16:00) y cierre (21:00) dependen del reloj del servidor |
| Red | Puerto de la app (8000) abierto a los usuarios de la intranet; salida al servidor de correo `smtp.etecsa.cu:25` para el parte diario |
| Paquetes Python | `pip install -r requirements-servidor.txt` (Django, DRF, psycopg, reportlab, openpyxl, waitress). Si el servidor no tiene internet, use el espejo interno de PyPI o descargue los paquetes en otro equipo con `pip download -r requirements-servidor.txt -d paquetes` e instálelos con `pip install --no-index --find-links paquetes -r requirements-servidor.txt` |

## 2. Base de datos (una sola vez)
```sql
CREATE ROLE mesa LOGIN PASSWORD 'UNA_CLAVE_FUERTE' CREATEDB;
CREATE DATABASE mesa_pruebas_db OWNER mesa ENCODING 'UTF8';
```
(`CREATEDB` solo se necesita para correr las pruebas automáticas; en producción puede quitarse.)

## 3. Instalación
```bash
# 1. Descomprima el paquete en, por ejemplo, C:\mesa_pruebas  (o /opt/mesa_pruebas)
python -m venv .venv
.venv\Scripts\pip install -r requirements-servidor.txt        # Linux: .venv/bin/pip

# 2. Configuración: copie .env.example como .env y complete los valores (ver comentarios dentro del archivo)
#    Obligatorios: POSTGRES_*, DJANGO_SECRET_KEY (50+ caracteres aleatorios), DJANGO_ALLOWED_HOSTS,
#    DJANGO_CSRF_TRUSTED_ORIGINS, DJANGO_HTTPS. Deje DJANGO_DEBUG=0.

# 3. Base de datos y datos iniciales
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py cargar_inicial      # brigadas, causas, claves con normas y roles (Probador, Especialista, Jefe)
.venv\Scripts\python manage.py createsuperuser     # administrador de la app
.venv\Scripts\python manage.py collectstatic --noinput   # estilos de /admin
```
Después, el administrador de la app crea en `/admin` los usuarios y los asigna a un grupo (Probador, Especialista o Jefe),
y carga **centros, vehículos, operarios** y los **destinatarios del parte diario**.

## 4. Arrancar la aplicación
```bash
.venv\Scripts\python servir.py          # escucha en el puerto SERVIDOR_PUERTO (8000)
```
Los usuarios abren `http(s)://<servidor>:8000/` en el navegador. En Windows, `iniciar_servidor.bat` hace lo mismo y anota en `logs\servidor.log`.

**Para que arranque solo y se reinicie si falla:**
- Windows: registrar `iniciar_servidor.bat` como servicio (p. ej. con NSSM: `nssm install MesaPruebas C:\mesa_pruebas\iniciar_servidor.bat`) o como tarea programada «Al iniciar el sistema».
- Linux: unidad `systemd` que ejecute `/opt/mesa_pruebas/.venv/bin/python servir.py` con `WorkingDirectory=/opt/mesa_pruebas` y `Restart=always`.

## 5. HTTPS (recomendado)
Las contraseñas viajan por la red: ponga la app detrás de **IIS (ARR), nginx o Apache** con certificado y reenvíe a `http://127.0.0.1:8000`. En ese caso, en el `.env`:
`DJANGO_HTTPS=1`, `DJANGO_TRAS_PROXY=1` (el proxy debe enviar `X-Forwarded-Proto: https`), `DJANGO_SSL_REDIRECT=0` si el proxy ya redirige de http a https, y
`DJANGO_CSRF_TRUSTED_ORIGINS=https://<nombre-de-la-app>`.
Si por ahora se usa **http sin certificado**: `DJANGO_HTTPS=0` (con `1` nadie podría iniciar sesión).

## 6. Tareas programadas (obligatorias)
| Hora | Qué hace | Windows | Linux (cron) |
|---|---|---|---|
| 16:00 | Envía el parte diario por correo (solo si ese día hubo hojas de ruta) | `enviar_informe.bat` | `0 16 * * * cd /opt/mesa_pruebas && .venv/bin/python manage.py enviar_informe_diario >> logs/informe_diario.log 2>&1` |
| 21:00 | Cierra las hojas que sigan abiertas | `cerrar_hojas_antiguas.bat` | `0 21 * * * cd /opt/mesa_pruebas && .venv/bin/python manage.py cerrar_hojas_antiguas >> logs/cerrar_hojas.log 2>&1` |
| 21:30 | Copia de seguridad de la base (`backups/`) | `respaldar_base.bat` | `30 21 * * * cd /opt/mesa_pruebas && .venv/bin/python manage.py respaldar_base >> logs/respaldo.log 2>&1` |

Windows (consola de administrador), una sola vez, ajustando la ruta:
```
schtasks /Create /SC DAILY /ST 16:00 /TN "UDAT Informe diario" /TR "C:\mesa_pruebas\enviar_informe.bat" /F
schtasks /Create /SC DAILY /ST 21:00 /TN "UDAT Cierre de hojas" /TR "C:\mesa_pruebas\cerrar_hojas_antiguas.bat" /F
schtasks /Create /SC DAILY /ST 21:30 /TN "UDAT Respaldo de la base" /TR "C:\mesa_pruebas\respaldar_base.bat" /F
```
Para que corran sin sesión iniciada, añada `/RU SYSTEM` (o una cuenta de servicio). `respaldar_base` necesita `pg_dump` (instalado con PostgreSQL; si no está en el PATH, defina `PG_DUMP` en el `.env`).

## 7. Copias de seguridad
- La copia diaria queda en `backups/` (14 más recientes). **Cópiela periódicamente a otro disco o equipo**.
- Restaurar en una base vacía: `pg_restore -h localhost -U mesa -d mesa_pruebas_db --no-owner backups/<archivo>.dump`

## 8. Actualizar a una versión nueva
1. Detenga la app. 2. Haga una copia (`manage.py respaldar_base`). 3. Reemplace los archivos (conserve `.env`, `backups/`, `logs/`).
4. `pip install -r requirements-servidor.txt` · `manage.py migrate` · `manage.py collectstatic --noinput` · `manage.py cargar_inicial` (actualiza los permisos de los roles).
5. Inicie la app.

## 9. Comprobaciones tras instalar
- `http(s)://<servidor>/` muestra la pantalla de inicio de sesión; `/admin/` abre con estilos.
- `manage.py check --deploy` no muestra avisos graves.
- `manage.py enviar_informe_diario --simular` indica a quién se enviaría (hace falta algún destinatario activo en `/admin`).
- `manage.py test` (opcional; usa una base temporal y necesita `CREATEDB`): todas las pruebas deben pasar.

## 10. Seguridad
- `DJANGO_SECRET_KEY` propia y secreta; `DJANGO_DEBUG=0`; el `.env` solo legible por la cuenta del servicio.
- El login admite 10 intentos por minuto y equipo (`LOGIN_LIMITE`).
- Cambie las claves de los usuarios iniciales y no comparta ningún volcado de la base: contiene datos y hashes de contraseñas.
