"""Carga del catálogo de gabinetes desde Excel: plantilla (con lo que ya hay cargado, para actualizarlo) e importación.

Una fila por gabinete y cable. Todo o nada: con algún error no se guarda nada. Los gabinetes del archivo se crean o se actualizan
(sus regletas se sustituyen por las del archivo); los que no estén en el archivo no se tocan."""
import io
import unicodedata

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Centro, Gabinete, RegletasDeGabinete

ENCABEZADOS = ["Gabinete", "Centro", "Cable", "Cantidad de regletas", "Pares por regleta", "Observaciones"]
PARES = (8, 10, 20)
MAXIMO_FILAS = 3000


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(texto.lower().split())


def _texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return " ".join(str(valor).split())


def plantilla_xlsx():
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Gabinetes"
    hoja.append(ENCABEZADOS)
    for g in Gabinete.objects.select_related("centro").prefetch_related("regletas").order_by("nombre"):
        centro = g.centro.codigo if g.centro else ""
        filas = list(g.regletas.all()) or [None]
        for r in filas:
            hoja.append([g.nombre, centro, r.cable if r else "", r.cantidad if r else None, r.pares if r else None, g.observaciones])
    for celda in hoja[1]:
        celda.font, celda.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F2A7A")
        celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for columna, ancho in zip("ABCDEF", (16, 10, 14, 22, 18, 40)):
        hoja.column_dimensions[columna].width = ancho
    hoja.freeze_panes = "A2"
    pares = DataValidation(type="list", formula1='"8,10,20"', allow_blank=True, showErrorMessage=True, error="Use 8, 10 o 20.")
    hoja.add_data_validation(pares)
    pares.add("E2:E3000")

    ayuda = libro.create_sheet("Instrucciones")
    centros = ", ".join(f"{c.codigo} ({c.nombre})" for c in Centro.objects.filter(activo=True).order_by("codigo"))
    for linea in [
        ["Escriba los datos en la hoja «Gabinetes», una fila por cada cable de cada gabinete."],
        ["Gabinete", "Obligatorio. Nombre con el que se le conoce: Ger3G, Ger4A, SH1B…"],
        ["Centro", "Opcional. Código del centro al que pertenece: " + centros],
        ["Cable", "Opcional. Cable que usa esas regletas. Déjelo vacío si solo conoce el total del gabinete."],
        ["Cantidad de regletas", "Opcional, pero sin ella la app no puede calcular el porcentaje de ejecución."],
        ["Pares por regleta", "Opcional: 8, 10 o 20. Si un cable usa regletas de distinta capacidad, ponga una fila por cada capacidad."],
        ["Observaciones", "Opcional. Del gabinete (basta con escribirlas en una de sus filas)."],
        [""],
        ["Ejemplo:", "Gabinete | Centro | Cable | Cantidad de regletas | Pares por regleta"],
        ["", "Ger3G | NG | 3 | 5 | 10"],
        ["", "Ger3G | NG | 4 | 2 | 20"],
        ["", "SH1B | CQ |  | 12 |"],
        [""],
        ["Al importar, los gabinetes del archivo se crean o se actualizan (sus filas sustituyen a las anteriores). Los que no estén en el archivo no cambian."],
        ["Para dejar de usar un gabinete, desmarque «activo» en la administración."],
    ]:
        ayuda.append(linea)
    ayuda.column_dimensions["A"].width = 22
    ayuda.column_dimensions["B"].width = 120
    memoria = io.BytesIO()
    libro.save(memoria)
    return memoria.getvalue()


def _leer(contenido):
    from openpyxl import load_workbook
    try:
        libro = load_workbook(io.BytesIO(contenido), data_only=True)
    except Exception as error:  # archivo dañado o que no es un Excel
        raise ValidationError("No se pudo leer el archivo: debe ser un Excel .xlsx.") from error
    hoja = libro["Gabinetes"] if "Gabinetes" in libro.sheetnames else libro.worksheets[0]
    filas = [list(f) for f in hoja.iter_rows(values_only=True)]
    if not filas:
        raise ValidationError("El archivo está vacío.")
    esperadas = {normalizar(t): i for i, t in enumerate(ENCABEZADOS)}
    columnas = {}
    for indice, titulo in enumerate(filas[0]):
        if normalizar(titulo) in esperadas:
            columnas.setdefault(ENCABEZADOS[esperadas[normalizar(titulo)]], indice)
    if "Gabinete" not in columnas:
        raise ValidationError("Falta la columna «Gabinete» en la primera fila. Use la plantilla.")
    datos = []
    for numero, fila in enumerate(filas[1:], start=2):
        d = {t: _texto(fila[columnas[t]]) if t in columnas and columnas[t] < len(fila) else "" for t in ENCABEZADOS}
        if any(d.values()):
            datos.append((numero, d))
    if not datos:
        raise ValidationError("El archivo no tiene gabinetes.")
    if len(datos) > MAXIMO_FILAS:
        raise ValidationError(f"El archivo tiene más de {MAXIMO_FILAS} filas.")
    return datos


@transaction.atomic
def importar(contenido):
    """Devuelve {"creados", "actualizados", "errores": [{"fila", "mensaje"}]}. Con errores no guarda nada."""
    centros = {}
    for c in Centro.objects.all():
        centros[normalizar(c.codigo)] = c
        centros[normalizar(c.nombre)] = c
    gabinetes, errores, vistas = {}, [], set()
    for numero, d in _leer(contenido):
        mensajes = []
        nombre = d["Gabinete"]
        if not nombre:
            mensajes.append("falta el nombre del gabinete")
        elif len(nombre) > 30:
            mensajes.append("el nombre del gabinete no puede pasar de 30 caracteres")
        centro = None
        if d["Centro"]:
            centro = centros.get(normalizar(d["Centro"]))
            if centro is None:
                mensajes.append(f"el centro «{d['Centro']}» no existe")
        cantidad = pares = None
        if d["Cantidad de regletas"]:
            if d["Cantidad de regletas"].isdigit() and 0 < int(d["Cantidad de regletas"]) <= 500:
                cantidad = int(d["Cantidad de regletas"])
            else:
                mensajes.append("la cantidad de regletas debe ser un número entre 1 y 500")
        if d["Pares por regleta"]:
            if d["Pares por regleta"].isdigit() and int(d["Pares por regleta"]) in PARES:
                pares = int(d["Pares por regleta"])
            else:
                mensajes.append("los pares por regleta deben ser 8, 10 o 20")
        if (d["Cable"] or pares) and not d["Cantidad de regletas"]:
            mensajes.append("indique la cantidad de regletas de ese cable")
        clave = normalizar(nombre)
        if nombre and cantidad:
            repetida = (clave, normalizar(d["Cable"]), pares)
            if repetida in vistas:
                mensajes.append("fila repetida para ese gabinete, cable y capacidad: súmelas en una sola")
            vistas.add(repetida)
        g = gabinetes.setdefault(clave, {"nombre": nombre, "centro": None, "observaciones": "", "regletas": []})
        if centro is not None:
            if g["centro"] is not None and g["centro"] != centro:
                mensajes.append("el mismo gabinete aparece con dos centros distintos")
            g["centro"] = centro
        g["observaciones"] = g["observaciones"] or d["Observaciones"][:200]
        if cantidad:
            g["regletas"].append((d["Cable"][:30], cantidad, pares))
        if mensajes:
            errores.append({"fila": numero, "mensaje": "; ".join(mensajes).capitalize() + "."})
    if errores:
        return {"creados": 0, "actualizados": 0, "errores": errores}
    creados = actualizados = 0
    for g in gabinetes.values():
        objeto = Gabinete.objects.filter(nombre__iexact=g["nombre"]).first()
        if objeto is None:
            objeto, creados = Gabinete(nombre=g["nombre"]), creados + 1
        else:
            actualizados += 1
        objeto.centro, objeto.observaciones = g["centro"], g["observaciones"]
        objeto.save()
        objeto.regletas.all().delete()
        RegletasDeGabinete.objects.bulk_create(RegletasDeGabinete(gabinete=objeto, cable=c, cantidad=n, pares=p) for c, n, p in g["regletas"])
    return {"creados": creados, "actualizados": actualizados, "errores": []}
