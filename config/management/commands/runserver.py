"""`manage.py runserver` con el puerto propio de este proyecto (PUERTO_DESARROLLO) y aviso si ya está ocupado.

Sin indicar puerto usa PUERTO_DESARROLLO (8001 por defecto, se cambia en el .env). Si algo ya escucha en ese puerto, no arranca y lo dice:
así dos proyectos no se pisan sin que nadie se entere."""
import os

from django.conf import settings
from django.contrib.staticfiles.management.commands.runserver import Command as RunserverCommand
from django.core.management.base import CommandError

from config.puertos import puerto_ocupado


class Command(RunserverCommand):
    default_port = str(settings.PUERTO_DESARROLLO)

    def run(self, **options):
        # el recargador automático vuelve a ejecutar el comando en un proceso hijo: solo se comprueba en el principal
        if os.environ.get("RUN_MAIN") != "true" and puerto_ocupado(self.port):
            raise CommandError(
                f"El puerto {self.port} ya está en uso por otro servidor (quizás de otro proyecto). "
                f"Use otro: python manage.py runserver {int(self.port) + 1}  (o fije PUERTO_DESARROLLO en el .env)."
            )
        super().run(**options)
