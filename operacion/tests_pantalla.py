import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings


class PantallaWebTests(SimpleTestCase):
    def test_sin_compilar_avisa_con_503(self):
        with tempfile.TemporaryDirectory() as d, override_settings(PANTALLA_DIR=Path(d)):
            r = self.client.get("/")
            self.assertEqual(r.status_code, 503)
            self.assertIn("npm", r.content.decode())

    def test_entrega_la_pantalla_compilada_y_sus_archivos(self):
        with tempfile.TemporaryDirectory() as d, override_settings(PANTALLA_DIR=Path(d)):
            (Path(d) / "index.html").write_text("<html>pantalla</html>", encoding="utf-8")
            (Path(d) / "assets").mkdir()
            (Path(d) / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
            (Path(d) / "logo.png").write_bytes(b"png")
            def pedir(ruta):  # lee y cierra la respuesta (en Windows un archivo abierto no deja borrar la carpeta temporal)
                r = self.client.get(ruta)
                cuerpo = b"".join(r.streaming_content) if r.streaming else r.content
                r.close()
                return r.status_code, cuerpo
            self.assertEqual(pedir("/"), (200, b"<html>pantalla</html>"))
            self.assertEqual(pedir("/assets/app.js"), (200, b"console.log(1)"))
            self.assertEqual(pedir("/logo.png")[0], 200)
            self.assertEqual(pedir("/no-existe.png")[0], 404)

    def test_la_api_y_el_admin_no_se_pisan(self):
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 403)
        self.assertEqual(self.client.get("/admin/login/").status_code, 200)
