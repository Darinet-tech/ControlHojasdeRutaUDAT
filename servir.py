"""Servidor de producción: `python servir.py`. Entrega la API, /admin y la pantalla web en un solo puerto.

Usa waitress si está instalado (pip install -r requirements-servidor.txt); si no, un servidor básico con hilos incluido en Python,
suficiente para unas decenas de usuarios internos."""
import os
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from config.wsgi import application  # noqa: E402  (después de fijar el módulo de configuración)


class _ServidorConHilos(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class _Silencioso(WSGIRequestHandler):
    def log_message(self, *args):  # sin una línea de log por cada petición
        pass


if __name__ == "__main__":
    puerto = int(os.environ.get("SERVIDOR_PUERTO", "8000"))
    try:
        from waitress import serve
    except ImportError:
        print(f"Mesa de Pruebas escuchando en el puerto {puerto} (servidor básico; Ctrl+C para detener)")
        make_server("0.0.0.0", puerto, application, server_class=_ServidorConHilos, handler_class=_Silencioso).serve_forever()
    else:
        print(f"Mesa de Pruebas escuchando en el puerto {puerto} (waitress; Ctrl+C para detener)")
        serve(application, host="0.0.0.0", port=puerto, threads=8)
