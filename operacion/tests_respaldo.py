import tempfile
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

BD = {"default": {"ENGINE": "django.db.backends.postgresql", "NAME": "mi_base", "USER": "u", "PASSWORD": "secreta", "HOST": "h", "PORT": "5432"}}


@override_settings(DATABASES=BD)
class RespaldoTests(SimpleTestCase):
    def falso_pg_dump(self, orden, **k):
        Path(orden[orden.index("-f") + 1]).write_bytes(b"datos")
        return mock.Mock(returncode=0, stderr="", stdout="")

    def test_guarda_la_copia_sin_poner_la_clave_en_la_linea_de_comandos(self):
        with tempfile.TemporaryDirectory() as d, mock.patch("subprocess.run", side_effect=self.falso_pg_dump) as run, \
                mock.patch("operacion.management.commands.respaldar_base.buscar_pg_dump", return_value="pg_dump"):
            call_command("respaldar_base", carpeta=d, verbosity=0)
            orden, entorno = run.call_args.args[0], run.call_args.kwargs["env"]
            self.assertNotIn("secreta", " ".join(orden))
            self.assertEqual(entorno["PGPASSWORD"], "secreta")
            self.assertEqual(len(list(Path(d).glob("mi_base_*.dump"))), 1)

    def test_conserva_solo_las_mas_recientes(self):
        with tempfile.TemporaryDirectory() as d, mock.patch("subprocess.run", side_effect=self.falso_pg_dump), \
                mock.patch("operacion.management.commands.respaldar_base.buscar_pg_dump", return_value="pg_dump"):
            for i in range(5):
                viejo = Path(d) / f"mi_base_2020-01-0{i + 1}_0000.dump"
                viejo.write_bytes(b"x")
                import os
                os.utime(viejo, (1000 + i, 1000 + i))
            call_command("respaldar_base", carpeta=d, conservar=3, verbosity=0)
            self.assertEqual(len(list(Path(d).glob("mi_base_*.dump"))), 3)

    def test_si_pg_dump_falla_no_deja_un_archivo_vacio(self):
        def falla(orden, **k):
            Path(orden[orden.index("-f") + 1]).write_bytes(b"")
            return mock.Mock(returncode=1, stderr="sin conexion", stdout="")
        with tempfile.TemporaryDirectory() as d, mock.patch("subprocess.run", side_effect=falla), \
                mock.patch("operacion.management.commands.respaldar_base.buscar_pg_dump", return_value="pg_dump"):
            with self.assertRaisesMessage(CommandError, "sin conexion"):
                call_command("respaldar_base", carpeta=d, verbosity=0)
            self.assertEqual(list(Path(d).iterdir()), [])
