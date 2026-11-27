"""Normas de tiempo de la «Instrucción de Trabajo: Actualización de las Normas de Tiempo de Especialidades de Red de Acceso (V2, 2026)».

La instrucción está en proceso de firma: las normas llevan esa nota y no una fecha de vigencia oficial (técnicamente rigen desde la fecha
base, que cubre cualquier hoja). Cuando se firme, el especialista puede cambiar la nota y las fechas en /admin.
Los tiempos van como «minutos:segundos», sin redondear, y son el total (intervención + documentación)."""
from datetime import date
from decimal import Decimal

INICIO = date(2000, 1, 1)
NOTA = "En proceso de firma"

# Totales corregidos respecto al documento: AS y REC (31:58), 22-G (24:27) y 26-M (24:00) estaban mal sumados;
# 07-ZC y 07-EC llevan 15 minutos de intervención. CTS y CD: 24 min; CMIS y CA, como CMONT (decisiones de la Mesa de Prueba).
TIPOS_ORDEN = {
    "A": "48:34", "AE": "48:34", "TA": "48:34", "TI": "48:34", "TE": "70:20", "B": "23:21", "BS": "17:24", "CPU": "21:30",
    "CL": "29:19", "CMONT": "29:19", "CMIS": "29:19", "CA": "29:19", "CVIV": "23:42", "CTS": "24:00", "CD": "24:00",
    "AS": "31:58", "REC": "31:58",
}
MANTENIMIENTOS = {"MPI": "40:00", "MPPI": "24:02", "MPPE": "27:48", "MTP": "22:47"}
# Gabinetes: no vienen en la instrucción. Acordado con la Mesa de Prueba: 50 min por cada regleta trabajada (mantenimiento, reparación o sustitución).
GAB_POR_REGLETA = "50:00"
NOTA_GAB = "Por regleta trabajada"

CLAVES = {
    "01-C": "16:00", "02-C": "16:00", "01-R": "18:29", "02-R": "18:29", "16-Z": "18:29", "24": "15:46",
    "23": "15:46", "23-C": "7:56", "24-C": "7:56", "09-C": "11:12", "21-R": "22:37", "21-ZR": "22:37",
    "21": "22:37", "21-Z": "22:37", "22-G": "24:27", "27-G": "16:47", "36": "9:53", "39": "9:53",
    "25": "15:00", "25-Z": "15:00", "38": "15:00", "37": "15:00", "07-ZC": "16:18", "07-EC": "16:18",
    "07-EP": "16:02", "07-ER": "16:02", "07-ZR": "16:02", "07-Z": "16:02", "07-IC": "17:53", "07-IP": "16:20",
    "07-IR": "16:20", "21-C": "9:25", "21-ZC": "9:25", "25-C": "22:06", "26-T": "22:06", "38-C": "22:06",
    "25-ZC": "22:06", "25-ZR": "3:27", "25-R": "3:27", "38-R": "3:27", "35-A": "9:16", "39-A": "9:16",
    "35-Z": "9:16", "39-Z": "9:16", "39-E": "9:16", "08-FA": "15:00", "60-A": "7:41", "15-Z": "1:00",
    "26-M": "24:00", "39-FA": "8:00", "14-R": "16:57", "14-RD": "7:37", "10DQ-TXD": "24:27", "18DD-TXD": "7:07",
    "1DMC-TXD": "43:51", "2DMF-TXD": "43:51", "20DE-TXD": "35:12", "21DC-TXD": "38:25", "27RI-TXD": "74:00", "5DH-TXD": "74:00",
    "39DA-TXD": "28:49", "35D-TXD": "28:49", "36D-TXD": "9:53", "39DF-TXD": "26:00", "3DS-TXD": "18:11", "4DR-TXD": "22:37",
    "8DA-TXD": "22:37", "9DI-TXD": "74:00",
}

# Tipos de orden nuevos: código, nombre, tipo del que toman la fila del parte diario
TIPOS_NUEVOS = [("CPU", "Cambio de puerta", "CVIV"), ("BS", "Baja suplementaria", "B")]


def minutos(texto):
    m, s = texto.split(":")
    return (Decimal(int(m) * 60 + int(s)) / 60).quantize(Decimal("0.0001"))


def crear_tipos_nuevos(TipoOrden):
    for codigo, nombre, como in TIPOS_NUEVOS:
        modelo = TipoOrden.objects.filter(codigo=como).first()
        TipoOrden.objects.get_or_create(codigo=codigo, defaults={"nombre": nombre, "fila_parte": modelo.fila_parte if modelo else ""})


def sustituir_normas(Clave, TipoOrden, TipoMantenimiento, NormaTiempo, NormaTipoOrden, NormaMantenimiento):
    """Reemplaza las normas de todo lo que trae la instrucción (lo demás conserva la suya). Se usa una sola vez, desde la migración."""
    def reemplazar(normas, filtro, tiempo):
        normas.objects.filter(**filtro).delete()
        normas.objects.create(minutos=minutos(tiempo), vigente_desde=INICIO, nota=NOTA, **filtro)

    for codigo, tiempo in CLAVES.items():
        for clave in Clave.objects.filter(codigo=codigo).exclude(ambito="ORDEN"):
            NormaTiempo.objects.filter(clave=clave, tipo_orden__isnull=True).delete()
            NormaTiempo.objects.create(clave=clave, minutos=minutos(tiempo), vigente_desde=INICIO, nota=NOTA)
    for codigo, tiempo in TIPOS_ORDEN.items():
        tipo = TipoOrden.objects.filter(codigo=codigo).first()
        if tipo:
            reemplazar(NormaTipoOrden, {"tipo_orden": tipo}, tiempo)
    for codigo, tiempo in MANTENIMIENTOS.items():
        tipo = TipoMantenimiento.objects.filter(codigo=codigo).first()
        if tipo:
            reemplazar(NormaMantenimiento, {"tipo_mantenimiento": tipo}, tiempo)
