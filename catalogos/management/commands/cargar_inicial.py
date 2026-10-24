"""Carga brigadas, causas de incidencia oficiales, centros, tipos de orden, claves de cierre (desde el CSV extraído del PDF), normas y roles.

Es idempotente: se puede ejecutar varias veces sin duplicar datos ni pisar cambios del administrador
en claves ya existentes (solo crea las que faltan).
"""
import csv
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction

from catalogos.models import (Brigada, CausaIncidencia, Centro, Clave, GrupoClave, NormaTiempo, TipoMantenimiento, TipoOrden,
                              TipoTrabajo)

BRIGADAS = ["Red de Abonados", "Reconstrucción", "Cable", "Línea", "Fibra Óptica"]
# Claves oficiales de incidencia.
CAUSAS = [
    ("100", "Lluvia"),
    ("101", "Traslado de personal"),
    ("102", "Esperando materiales"),
    ("105", "Esperando por probador"),
    ("106", "Problemas con el transporte"),
    ("107", "Realizando actividades comerciales"),
    ("108", "Otras causas"),
    ("110", "Autorizado por el jefe"),
]
# Centros conocidos (el administrador agrega el resto desde la administración).
CENTROS = [("NG", "Nueva Gerona"), ("FI", "La Fé"), ("FO", "La Reforma")]
INICIO_NORMAS = date(2000, 1, 1)  # cubre cualquier fecha histórica que se importe después

ROLES = {
    "Probador": {
        "operacion": (["hojaderuta", "ordenservicio", "accion", "incidencia"], ["add", "change", "view"]),
        "catalogos": (["brigada", "centro", "vehiculo", "operario", "clave", "normatiempo", "tipoorden",
                       "causaincidencia", "grupoclave", "tipomantenimiento", "tipotrabajo", "normatrabajo"], ["view"]),
    },
    "Especialista": {
        "catalogos": (["brigada", "centro", "vehiculo", "operario", "clave", "normatiempo", "tipoorden",
                       "causaincidencia", "grupoclave", "tipomantenimiento", "tipotrabajo", "normatrabajo"], ["add", "change", "delete", "view"]),
        "operacion": (["hojaderuta", "ordenservicio", "accion", "incidencia"], ["view"]),
    },
    "Jefe": {
        "catalogos": (["brigada", "centro", "vehiculo", "operario", "clave", "normatiempo", "tipoorden",
                       "causaincidencia", "grupoclave", "tipomantenimiento", "tipotrabajo", "normatrabajo"], ["view"]),
        "operacion": (["hojaderuta", "ordenservicio", "accion", "incidencia"], ["view"]),
    },
}


# Definido por el negocio (no por el PDF, que tiene errores): estas claves NO restablecen el servicio.
NO_EFECTIVAS = {"01", "02", "14-P", "21", "22", "23", "24", "25", "27", "29", "36", "36-V", "36D-TXD", "37", "38",
                "39", "70"}
# Claves del PDF que el negocio eliminó del catálogo.
EXCLUIDAS = {"09-R", "39-W", "63-X"}
# Claves repetidas en el PDF (Datos y Reparador): se conserva solo la de Datos.
DUPLICADAS_SOLO_DATOS = {"11DW-TXD", "1DMC-TXD", "3DS-TXD"}
# El PDF las daba como "No efectiva" pero no están en la lista del negocio: pasan a Efectiva y se marcan para confirmar.
RECLASIFICADAS_A_EFECTIVA = {"07-EP", "07-IP", "08", "09", "35-D"}

TIPOS_MANTENIMIENTO = [
    ("MPPI", "Mantenimiento Preventivo Parcial Interior"),
    ("MPPE", "Mantenimiento Preventivo Parcial Exterior"),
    ("MPI", "Mantenimiento Preventivo Integral"),
]
# Trabajos de las órdenes de trabajo: los especialistas agregan los demás y sus normas de tiempo.
TIPOS_TRABAJO = ["Sustitución de poste(s)", "Sustitución de caja(s) terminal(es)"]

TIPOS_ORDEN = [
    ("A", "Alta"),
    ("TA", "Traslado con cambio de central"),
    ("TE", "Traslado con cambio de disponibilidad en la misma central"),
    ("TI", "Traslado que mantiene la misma facilidad"),
    ("AS", "Alta suplementaria"),
    ("B", "Baja"),
    ("AE", "Alta eventual"),
    ("CL", "Cambio de lugar"),
    ("CMONT", "Cambio de montaje"),
    ("REC", "Reconstrucción"),
    ("CTS", "Cambio de tipo de servicio"),
    ("CVIV", "Cambio de velocidad"),
]


def clasificar(fila):
    """Devuelve (clasificación, revisar). La clasificación PENDIENTE no se asigna aquí: la decide el probador por caso."""
    codigo = fila["codigo"].strip()
    clas = Clave.Clasificacion.NO_EFECTIVA if codigo in NO_EFECTIVAS else Clave.Clasificacion.EFECTIVA
    revisar = codigo in RECLASIFICADAS_A_EFECTIVA
    return clas, revisar


class Command(BaseCommand):
    help = "Carga datos iniciales: brigadas, causas, claves de cierre con sus normas y roles."

    def add_arguments(self, parser):
        parser.add_argument("--csv", default=str(Path(settings.BASE_DIR) / "data" / "claves_cierre.csv"))

    @transaction.atomic
    def handle(self, *args, **opts):
        for nombre in BRIGADAS:
            Brigada.objects.get_or_create(nombre=nombre)
        for codigo, nombre in CAUSAS:
            CausaIncidencia.objects.get_or_create(codigo=codigo, defaults={"nombre": nombre})
        for codigo, nombre in CENTROS:
            Centro.objects.get_or_create(codigo=codigo, defaults={"nombre": nombre})
        for codigo, nombre in TIPOS_MANTENIMIENTO:
            TipoMantenimiento.objects.get_or_create(codigo=codigo, defaults={"nombre": nombre})
        for nombre in TIPOS_TRABAJO:
            TipoTrabajo.objects.get_or_create(nombre=nombre)
        for codigo, nombre in TIPOS_ORDEN:
            TipoOrden.objects.get_or_create(codigo=codigo, defaults={"nombre": nombre})

        creadas = 0
        with open(opts["csv"], newline="", encoding="utf-8") as f:
            for fila in csv.DictReader(f):
                codigo = fila["codigo"].strip()
                if codigo in EXCLUIDAS:
                    continue
                if codigo in DUPLICADAS_SOLO_DATOS and fila["grupo"].strip() != "Datos":
                    continue
                if Clave.objects.filter(codigo=codigo).exists():
                    continue  # no se pisan los cambios que haya hecho el administrador
                grupo, _ = GrupoClave.objects.get_or_create(nombre=fila["grupo"].strip())
                clas, revisar = clasificar(fila)
                clave = Clave.objects.create(
                    codigo=codigo, grupo=grupo, descripcion=fila["descripcion"], clasificacion=clas, revisar=revisar
                )
                NormaTiempo.objects.create(clave=clave, minutos=int(fila["tiempo_min"]), vigente_desde=INICIO_NORMAS)
                creadas += 1

        self._roles()
        self.stdout.write(self.style.SUCCESS(
            f"Claves creadas: {creadas}; total en catálogo: {Clave.objects.count()}; "
            f"por revisar: {Clave.objects.filter(revisar=True).count()}"
        ))

    def _roles(self):
        for nombre, apps in ROLES.items():
            grupo, _ = Group.objects.get_or_create(name=nombre)
            codenames = [f"{a}_{m}" for app, (modelos, acciones) in apps.items() for m in modelos for a in acciones]
            grupo.permissions.set(Permission.objects.filter(codename__in=codenames,
                                                            content_type__app_label__in=list(apps)))
