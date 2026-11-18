"""Normas de tiempo por tipo de orden de servicio y por tipo de mantenimiento (documento «Normas de Tiempo», revisión Morales, 4 marzo 2015).

Faltan en el documento: CMONT (orden) y GAB (mantenimiento): quedan sin norma hasta que el administrador la defina en /admin.
Solo se crean donde no hay ninguna norma: no se pisan los cambios del administrador."""
from datetime import date

INICIO = date(2000, 1, 1)  # cubre cualquier fecha histórica, como las normas de las claves
NORMAS_TIPO_ORDEN = {"A": 50, "AS": 25, "CL": 25, "B": 35, "TA": 50, "TE": 50, "TI": 50, "REC": 25, "CMIS": 25, "AE": 50,
                     "CA": 30, "CVIV": 30, "CTS": 30, "CD": 30}
NORMAS_MANTENIMIENTO = {"MPI": 55, "MPPI": 25, "MPPE": 30, "MTP": 25}


def crear(TipoOrden, TipoMantenimiento, NormaTipoOrden, NormaMantenimiento):
    for codigo, minutos in NORMAS_TIPO_ORDEN.items():
        tipo = TipoOrden.objects.filter(codigo=codigo).first()
        if tipo and not NormaTipoOrden.objects.filter(tipo_orden=tipo).exists():
            NormaTipoOrden.objects.create(tipo_orden=tipo, minutos=minutos, vigente_desde=INICIO)
    for codigo, minutos in NORMAS_MANTENIMIENTO.items():
        tipo = TipoMantenimiento.objects.filter(codigo=codigo).first()
        if tipo and not NormaMantenimiento.objects.filter(tipo_mantenimiento=tipo).exists():
            NormaMantenimiento.objects.create(tipo_mantenimiento=tipo, minutos=minutos, vigente_desde=INICIO)
