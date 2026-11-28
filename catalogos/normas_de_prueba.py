"""Solo para las pruebas: normas con números redondos y fijos.

Las pruebas de cálculo (productividad, resúmenes, informes) no deben depender de los tiempos oficiales, que cambian cuando se firma o se
actualiza una instrucción. Los valores oficiales se comprueban aparte (catalogos/tests_normas.py)."""
import csv
from pathlib import Path

from django.conf import settings

from .models import NormaMantenimiento, NormaTiempo, NormaTipoOrden, TipoMantenimiento, TipoOrden
from .normas_tipo import INICIO, crear


def fijar():
    with open(Path(settings.BASE_DIR) / "data" / "claves_cierre.csv", newline="", encoding="utf-8") as f:
        minutos = {fila["codigo"].strip(): int(fila["tiempo_min"]) for fila in csv.DictReader(f) if fila["tiempo_min"].strip()}
    for norma in NormaTiempo.objects.select_related("clave"):
        if norma.clave.codigo in minutos:
            NormaTiempo.objects.filter(pk=norma.pk).update(minutos=minutos[norma.clave.codigo], vigente_desde=INICIO, nota="")
    trabajos_de_prueba()
    TipoOrden.objects.filter(codigo__in=["CPU", "BS"]).delete()  # tipos posteriores: no están en los números de prueba
    NormaTipoOrden.objects.all().delete()
    NormaMantenimiento.objects.all().delete()
    crear(TipoOrden, TipoMantenimiento, NormaTipoOrden, NormaMantenimiento)


def trabajos_de_prueba():
    """Tres trabajos sencillos para las pruebas de cálculo (postes por unidad, caja terminal a 70 min por caja y cable por metro)."""
    from datetime import date

    from .models import NormaTrabajo, TipoTrabajo
    for nombre, medida, unidad in (("Sustitución de poste(s)", "UNIDADES", "poste(s)"), ("Sustitución de caja(s) terminal(es)", "UNIDADES", "caja(s)"),
                                   ("Sustitución de cable de cobre", "METROS", "metro(s)")):
        trabajo, _ = TipoTrabajo.objects.get_or_create(nombre=nombre, defaults={"medida": medida, "unidad": unidad})
        if nombre.startswith("Sustitución de caja") and not NormaTrabajo.objects.filter(tipo_trabajo=trabajo).exists():
            NormaTrabajo.objects.create(tipo_trabajo=trabajo, minutos=70, vigente_desde=date(2000, 1, 1))


def trabajo_por_tipo():
    """Trabajo de prueba «según el tipo» (como el que usaría un especialista): Multiservicios 70 min y Con cola 100 min."""
    from datetime import date

    from .models import NormaTrabajo, OpcionDeTrabajo, TipoTrabajo
    trabajo, creado = TipoTrabajo.objects.get_or_create(nombre="Sustitución de caja por tipo (prueba)", defaults={"medida": "TIPO"})
    if creado:
        for nombre, minutos in (("Multiservicios", 70), ("Con cola", 100)):
            opcion = OpcionDeTrabajo.objects.create(tipo_trabajo=trabajo, nombre=nombre)
            NormaTrabajo.objects.create(tipo_trabajo=trabajo, opcion=opcion, minutos=minutos, vigente_desde=date(2000, 1, 1))
    return trabajo

