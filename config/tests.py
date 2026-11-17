import socket

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from config.management.commands.runserver import Command
from config.puertos import puerto_ocupado


class PuertoDelProyectoTests(SimpleTestCase):
    def test_el_servidor_de_desarrollo_usa_el_puerto_del_proyecto(self):
        self.assertEqual(Command.default_port, str(settings.PUERTO_DESARROLLO))

    def test_las_cookies_tienen_nombre_propio(self):
        self.assertEqual((settings.SESSION_COOKIE_NAME, settings.CSRF_COOKIE_NAME), ("mesa_sessionid", "mesa_csrftoken"))

    def test_detecta_un_puerto_ocupado_y_se_niega_a_arrancar(self):
        with socket.socket() as ocupado:
            ocupado.bind(("127.0.0.1", 0))
            ocupado.listen()
            puerto = ocupado.getsockname()[1]
            self.assertTrue(puerto_ocupado(puerto))
            with self.assertRaisesMessage(CommandError, f"El puerto {puerto} ya está en uso"):
                call_command("runserver", f"127.0.0.1:{puerto}", use_reloader=False)

    def test_un_puerto_libre_no_figura_como_ocupado(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            libre = s.getsockname()[1]
        self.assertFalse(puerto_ocupado(libre))
