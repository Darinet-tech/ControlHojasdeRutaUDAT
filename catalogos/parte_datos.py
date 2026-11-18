"""Valores por defecto de la fila del parte diario que le corresponde a cada clave, tipo de orden y tipo de mantenimiento.

Se aplican solo donde el campo está en blanco: lo que el administrador cambie en /admin no se pisa."""

CLAVES_PENDIENTE_PAR = {"23", "24"}
CLAVES_OTRAS_CAUSAS = {"01", "02", "14-P", "21", "22", "25", "27", "29", "36", "36-V", "36D-TXD", "37", "38", "39"}

TIPO_ORDEN_FILA = {
    "A": "ALTAS", "AE": "ALTAS", "TA": "TRASLADOS", "B": "BAJAS", "TE": "TE_TI", "TI": "TE_TI",
    "AS": "MISC", "CL": "MISC", "CMONT": "MISC", "CMIS": "MISC", "REC": "MISC",
    "CTS": "TXD", "CVIV": "TXD", "CD": "TXD", "CA": "TXD",
}
TIPO_MANTENIMIENTO_FILA = {"MPI": "MANT_RED", "MPPI": "MANT_RED", "MPPE": "MANT_RED", "MTP": "MANT_TP", "GAB": "GABINETES"}

# Tipos nuevos que pide el parte (si faltan se crean): código, nombre
TIPOS_ORDEN_NUEVOS = [("CMIS", "Cambio misceláneo (CMIS)"), ("CD", "Cambio de dirección"), ("CA", "Cambio de aparato")]
TIPOS_MANTENIMIENTO_NUEVOS = [("MTP", "Mantenimiento de Telefonía Pública"), ("GAB", "Mantenimiento de Gabinetes")]


def completar(Clave, TipoOrden, TipoMantenimiento):
    """Crea los tipos que faltan y rellena la fila del parte en los registros que la tienen en blanco."""
    for codigo, nombre in TIPOS_ORDEN_NUEVOS:
        TipoOrden.objects.get_or_create(codigo=codigo, defaults={"nombre": nombre})
    for codigo, nombre in TIPOS_MANTENIMIENTO_NUEVOS:
        TipoMantenimiento.objects.get_or_create(codigo=codigo, defaults={"nombre": nombre})
    Clave.objects.filter(fila_parte="", codigo__in=CLAVES_PENDIENTE_PAR).update(fila_parte="PENDIENTE_PAR")
    Clave.objects.filter(fila_parte="", codigo__in=CLAVES_OTRAS_CAUSAS).update(fila_parte="OTRAS_CAUSAS")
    for codigo, fila in TIPO_ORDEN_FILA.items():
        TipoOrden.objects.filter(fila_parte="", codigo=codigo).update(fila_parte=fila)
    for codigo, fila in TIPO_MANTENIMIENTO_FILA.items():
        TipoMantenimiento.objects.filter(fila_parte="", codigo=codigo).update(fila_parte=fila)
