"""Trabajos de las órdenes de trabajo: las actividades de Cable y de Línea de la instrucción firmada IT-OR-001/24 y los trabajos propios.

Cada actividad de la instrucción se norma «por unidad» o «por metro»: el probador anota la cantidad y la norma de la orden es la **suma** de sus
actividades. Los tiempos van sin redondear y con la nota de la instrucción (válida hasta el 16/7/2026, hasta que se firme su renovación)."""
import json
from pathlib import Path

from .normas_2026 import INICIO, NOTA, minutos

ARCHIVO = Path(__file__).with_name("actividades_cable_linea.json")

# Trabajos propios de la Mesa de Prueba (anteriores a la carga de la instrucción): nombre, cómo se norma, unidad.
PROPIOS = [
    ("Sustitución de poste(s)", "UNIDADES", "poste(s)"),
    ("Sustitución de caja(s) terminal(es)", "UNIDADES", "caja(s)"),
    ("Sustitución de cable de cobre", "METROS", "metro(s)"),
]
# La sustitución de una caja terminal se norma como en la instrucción (Cable 18: 70 min); el módulo de empalme y los pares empalmados
# se suman con sus propias actividades (Cable 76 y Cable 48).
CAJA = "Sustitución de caja(s) terminal(es)"
MINUTOS_CAJA = "70:00"


def cargar_actividades(TipoTrabajo, NormaTrabajo):
    """Crea (o completa) las actividades de la instrucción con su norma. No pisa lo que el especialista haya cambiado: solo crea lo que falta."""
    creadas = 0
    for a in json.loads(ARCHIVO.read_text(encoding="utf-8")):
        trabajo = TipoTrabajo.objects.filter(especialidad=a["especialidad"], clave=a["clave"]).first()
        if trabajo is None:
            trabajo = TipoTrabajo.objects.create(
                nombre=a["nombre"], especialidad=a["especialidad"], clave=a["clave"], medida=a["medida"], unidad=a["unidad"],
                fuerza_trabajo=a["fuerza_trabajo"], descripcion=a["descripcion"])
            creadas += 1
        if not NormaTrabajo.objects.filter(tipo_trabajo=trabajo, opcion__isnull=True).exists():
            NormaTrabajo.objects.create(tipo_trabajo=trabajo, minutos=round(a["minutos"], 4), vigente_desde=INICIO, nota=NOTA)
    return creadas


def configurar(TipoTrabajo, OpcionDeTrabajo, NormaTrabajo):
    """Crea los trabajos propios que falten (con su forma de medirse, solo si no la tienen) y carga las actividades de la instrucción."""
    for nombre, medida, unidad in PROPIOS:
        trabajo, _ = TipoTrabajo.objects.get_or_create(nombre=nombre)
        if not trabajo.medida:
            trabajo.medida, trabajo.unidad = medida, unidad
            trabajo.save()
    caja = TipoTrabajo.objects.get(nombre=CAJA)
    if caja.medida == "UNIDADES" and not NormaTrabajo.objects.filter(tipo_trabajo=caja, opcion__isnull=True).exists():
        NormaTrabajo.objects.create(tipo_trabajo=caja, minutos=minutos(MINUTOS_CAJA), vigente_desde=INICIO, nota=NOTA)
    cargar_actividades(TipoTrabajo, NormaTrabajo)


def caja_segun_la_instruccion(TipoTrabajo, OpcionDeTrabajo, NormaTrabajo):
    """Base que ya tenía la caja terminal «según el tipo» (Multiservicios / Con cola): pasa a la norma de la instrucción y las opciones se desactivan."""
    caja = TipoTrabajo.objects.filter(nombre=CAJA).first()
    if caja is None or caja.medida != "TIPO":
        return
    caja.medida, caja.unidad = "UNIDADES", "caja(s)"
    caja.save()
    OpcionDeTrabajo.objects.filter(tipo_trabajo=caja).update(activa=False)
    NormaTrabajo.objects.filter(tipo_trabajo=caja, opcion__isnull=True).delete()
    NormaTrabajo.objects.create(tipo_trabajo=caja, minutos=minutos(MINUTOS_CAJA), vigente_desde=INICIO, nota=NOTA)
