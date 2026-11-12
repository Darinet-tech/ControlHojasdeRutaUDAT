"""Copia de seguridad de la base de datos PostgreSQL (pg_dump) en la carpeta backups/, con la fecha en el nombre."""
import glob
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


def buscar_pg_dump():
    """pg_dump del PATH, de la variable PG_DUMP, o de la instalación más reciente de PostgreSQL en Windows."""
    if os.environ.get("PG_DUMP"):
        return os.environ["PG_DUMP"]
    en_path = shutil.which("pg_dump")
    if en_path:
        return en_path
    instalados = sorted(glob.glob(r"C:\Program Files\PostgreSQL\*\bin\pg_dump.exe"),
                        key=lambda r: int(Path(r).parts[-3]) if Path(r).parts[-3].isdigit() else 0)
    return instalados[-1] if instalados else None


class Command(BaseCommand):
    help = "Guarda una copia de la base de datos en backups/ (formato pg_dump -Fc) y conserva solo las más recientes."

    def add_arguments(self, parser):
        parser.add_argument("--conservar", type=int, default=14, help="Cuántas copias conservar (por defecto, 14)")
        parser.add_argument("--carpeta", default=str(Path(settings.BASE_DIR) / "backups"), help="Carpeta de destino")

    def handle(self, *args, **opciones):
        bd = settings.DATABASES["default"]
        if "postgresql" not in bd["ENGINE"]:
            raise CommandError("La copia de seguridad solo está preparada para PostgreSQL (la base actual es SQLite: copie db.sqlite3).")
        pg_dump = buscar_pg_dump()
        if not pg_dump:
            raise CommandError("No se encontró pg_dump. Instale las herramientas de PostgreSQL o defina PG_DUMP en el .env.")
        carpeta = Path(opciones["carpeta"])
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / f"{bd['NAME']}_{datetime.now():%Y-%m-%d_%H%M}.dump"
        entorno = {**os.environ, "PGPASSWORD": bd.get("PASSWORD") or ""}  # la clave no va en la línea de comandos
        orden = [pg_dump, "-h", bd["HOST"], "-p", str(bd["PORT"]), "-U", bd["USER"], "-Fc", "-f", str(destino), bd["NAME"]]
        resultado = subprocess.run(orden, env=entorno, capture_output=True, text=True)
        if resultado.returncode != 0 or not destino.exists() or destino.stat().st_size == 0:
            destino.unlink(missing_ok=True)
            raise CommandError(f"pg_dump falló: {(resultado.stderr or resultado.stdout).strip()}")
        antiguas = sorted(carpeta.glob(f"{bd['NAME']}_*.dump"), key=lambda r: r.stat().st_mtime, reverse=True)[opciones["conservar"]:]
        for vieja in antiguas:
            vieja.unlink()
        self.stdout.write(self.style.SUCCESS(f"Copia guardada: {destino} ({destino.stat().st_size // 1024} KB). "
                                             f"Se conservan las {opciones['conservar']} más recientes; borradas: {len(antiguas)}."))
