"""Arma el paquete para entregar a TI: `python empaquetar_entrega.py` -> entrega/MesaPruebas_AAAA-MM-DD.zip

Incluye el código versionado en git y la pantalla ya compilada (frontend/dist). Nunca incluye .env, copias de seguridad,
logs, bases SQLite, .venv ni node_modules."""
import shutil
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DIST = RAIZ / "frontend" / "dist"
EXCLUIR = ("backups/", "logs/", ".venv/", "node_modules/", "staticfiles/", "entrega/", "logos/")
EXCLUIR_EXACTOS = {".env", "db.sqlite3"}


def main():
    npm = shutil.which("npm")
    if npm:
        print("Compilando la pantalla web...")
        subprocess.run([npm, "run", "build"], cwd=RAIZ / "frontend", check=True)
    if not (DIST / "index.html").exists():
        sys.exit("Falta frontend/dist: instale Node.js y ejecute 'npm ci && npm run build' en la carpeta frontend.")
    sucios = subprocess.run(["git", "status", "--porcelain"], cwd=RAIZ, capture_output=True, text=True).stdout.strip()
    if sucios:
        print("AVISO: hay cambios sin confirmar en git; el paquete lleva la versión del último commit, no esos cambios.")
    archivos = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, check=True).stdout.splitlines()
    archivos = [a for a in archivos if not a.startswith(EXCLUIR) and a not in EXCLUIR_EXACTOS and not a.endswith((".sql", ".dump"))]
    (RAIZ / "entrega").mkdir(exist_ok=True)
    destino = RAIZ / "entrega" / f"MesaPruebas_{date.today():%Y-%m-%d}.zip"
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for a in archivos:
            z.write(RAIZ / a, f"mesa_pruebas/{a}")
        for f in DIST.rglob("*"):
            if f.is_file():
                z.write(f, f"mesa_pruebas/frontend/dist/{f.relative_to(DIST).as_posix()}")
    print(f"Paquete listo: {destino} ({destino.stat().st_size // 1024} KB, {len(archivos)} archivos de código + pantalla compilada)")


if __name__ == "__main__":
    main()
