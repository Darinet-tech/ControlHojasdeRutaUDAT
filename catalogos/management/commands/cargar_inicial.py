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

from catalogos.claves_orden import crear as crear_claves_de_orden
from catalogos import normas_2026, trabajos
from catalogos.parte_datos import completar as completar_filas_parte
from catalogos.models import (NormaTrabajo, Brigada, CausaIncidencia, Centro, Clave, GrupoClave, NormaMantenimiento, NormaTiempo, NormaTipoOrden,
                              TipoMantenimiento, TipoOrden,
                              TipoTrabajo)

BRIGADAS = ["Red de Abonados", "Reconstrucción", "Cable", "Línea", "Fibra Óptica"]
# Claves oficiales de incidencia.
# Causas de incidencia (anexo 2 de la IT-OR-001/24, AT-1): código, nombre y si descuenta tiempo. 105, 107, 111 y 112 cuentan como tiempo efectivo.
CAUSAS = [
    ("100", "Lluvia", True),
    ("101", "Traslado de personal", True),
    ("102", "Esperando materiales", True),
    ("105", "Esperando por probador", False),
    ("106", "Problemas con el transporte", True),
    ("107", "Realizando actividades comerciales", False),
    ("108", "Otras causas", True),
    ("110", "Autorizado por el jefe", True),
    ("111", "Tiempo de poda", False),
    ("112", "Tiempo trasladado", False),
]
# Centros conocidos (el administrador agrega el resto desde la administración).
CENTROS = [("NG", "Nueva Gerona"), ("FI", "La Fé"), ("FO", "La Reforma")]
INICIO_NORMAS = date(2000, 1, 1)  # cubre cualquier fecha histórica que se importe después

ROLES = {
    "Probador": {
        "operacion": (["hojaderuta", "ordenservicio", "accion", "incidencia"], ["add", "change", "view"]),
        "catalogos": (["brigada", "centro", "vehiculo", "operario", "clave", "claveordenservicio", "normatiempo", "tipoorden",
                       "causaincidencia", "grupoclave", "tipomantenimiento", "tipotrabajo", "normatrabajo", "gabinete", "regletasdegabinete"], ["view"]),
    },
    "Especialista": {
        "catalogos": (["brigada", "centro", "vehiculo", "operario", "clave", "claveordenservicio", "normatiempo", "tipoorden",
                       "causaincidencia", "grupoclave", "tipomantenimiento", "tipotrabajo", "normatrabajo", "gabinete", "regletasdegabinete"], ["add", "change", "delete", "view"]),
        "operacion": (["hojaderuta", "ordenservicio", "accion", "incidencia"], ["view"]),
    },
    "Jefe": {
        "catalogos": (["brigada", "centro", "vehiculo", "operario", "clave", "claveordenservicio", "normatiempo", "tipoorden",
                       "causaincidencia", "grupoclave", "tipomantenimiento", "tipotrabajo", "normatrabajo", "gabinete", "regletasdegabinete"], ["view"]),
        "operacion": (["hojaderuta", "ordenservicio", "accion", "incidencia"], ["view"]),
    },
}


# Permisos a medida (no siguen el patrón añadir/cambiar/ver): el jefe puede reabrir una hoja cerrada.
PERMISOS_EXTRA = {"Jefe": ["reabrir_hojaderuta"]}

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
            Brigada.objects.get_or_create(nombre=nombre, defaults={"informa_con_texto": nombre == "Línea"})
        for codigo, nombre, descuenta in CAUSAS:
            CausaIncidencia.objects.get_or_create(codigo=codigo, defaults={"nombre": nombre, "descuenta_tiempo": descuenta})
        for codigo, nombre in CENTROS:
            Centro.objects.get_or_create(codigo=codigo, defaults={"nombre": nombre})
        for codigo, nombre in TIPOS_MANTENIMIENTO:
            TipoMantenimiento.objects.get_or_create(codigo=codigo, defaults={"nombre": nombre})
        trabajos.cargar_actividades(TipoTrabajo, NormaTrabajo)  # actividades de las órdenes de trabajo (Cable, Línea y Fibra Óptica)
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
                nueva = normas_2026.CLAVES.get(codigo)  # las de la instrucción vigente; las demás claves, las del catálogo anterior
                NormaTiempo.objects.create(clave=clave, vigente_desde=INICIO_NORMAS,
                                           minutos=normas_2026.minutos(nueva) if nueva else int(fila["tiempo_min"]),
                                           nota=normas_2026.NOTA if nueva else "")
                creadas += 1

        crear_claves_de_orden(Clave, GrupoClave)  # claves de cierre de las órdenes de servicio (1 a 19)
        completar_filas_parte(Clave, TipoOrden, TipoMantenimiento)  # tipos del parte (MTP, GAB, CMIS) y fila de cada clave/tipo
        normas_2026.crear_tipos_nuevos(TipoOrden)  # CPU y BS
        for modelo, normas, campo, tabla in ((TipoOrden, NormaTipoOrden, "tipo_orden", normas_2026.TIPOS_ORDEN),
                                             (TipoMantenimiento, NormaMantenimiento, "tipo_mantenimiento", normas_2026.MANTENIMIENTOS)):
            for codigo, tiempo in tabla.items():  # solo donde no hay ninguna norma: no se pisan los cambios del administrador
                tipo = modelo.objects.filter(codigo=codigo).first()
                if tipo and not normas.objects.filter(**{campo: tipo}).exists():
                    normas.objects.create(minutos=normas_2026.minutos(tiempo), vigente_desde=normas_2026.INICIO, nota=normas_2026.NOTA, **{campo: tipo})
        gabinete = TipoMantenimiento.objects.filter(codigo="GAB").first()
        if gabinete and not NormaMantenimiento.objects.filter(tipo_mantenimiento=gabinete).exists():
            NormaMantenimiento.objects.create(tipo_mantenimiento=gabinete, minutos=normas_2026.minutos(normas_2026.GAB_POR_REGLETA),
                                              vigente_desde=normas_2026.INICIO, nota=normas_2026.NOTA_GAB)
        self._roles()
        self.stdout.write(self.style.SUCCESS(
            f"Claves creadas: {creadas}; total en catálogo: {Clave.objects.count()}; "
            f"por revisar: {Clave.objects.filter(revisar=True).count()}"
        ))

    def _roles(self):
        for nombre, apps in ROLES.items():
            grupo, _ = Group.objects.get_or_create(name=nombre)
            codenames = [f"{a}_{m}" for app, (modelos, acciones) in apps.items() for m in modelos for a in acciones]
            codenames += PERMISOS_EXTRA.get(nombre, [])
            grupo.permissions.set(Permission.objects.filter(codename__in=codenames,
                                                            content_type__app_label__in=list(apps)))
