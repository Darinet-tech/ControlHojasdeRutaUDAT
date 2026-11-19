"""Importación de las acciones de una hoja desde un archivo Excel (.xlsx) o CSV, para no tener que insertarlas una a una.

El archivo tiene una fila por servicio y estas columnas (los nombres admiten mayúsculas, tildes y alias; las columnas que sobren se ignoran):

- tipo (obligatoria): Correctivo, Preventivo, Orden de servicio u Orden de trabajo (también C, P, OS, OT).
- servicio: número del servicio telefónico (correctivo, preventivo y orden de servicio).
- tipo de orden: código del tipo (A, B, TA...), solo en órdenes de servicio.
- orden: número de la orden (órdenes de servicio y de trabajo).
- mantenimiento: código del tipo de mantenimiento (MPI, MPPE, MTP, GAB...), solo en preventivos.
- variante (opcional): TP (Telefonía Pública) o NH+ en correctivos; NH en altas de orden de servicio.
- centro (opcional): código del centro, si la hoja trabaja en varios.
- trabajos (órdenes de trabajo): nombres de los trabajos separados por «;».

**Planificación diaria**: si el archivo no tiene columna «tipo» pero sí «servicio» (como el Excel de planificación diaria, cuyo encabezado puede
estar en la segunda fila), solo se usa la columna SERVICIO y todo se importa como correctivo. Los espacios del número se quitan («46 315207» → «46315207», «NG ED190069» → «NGED190069»). Las filas de horario («11:00 – 02:00 PM») y las vacías se saltan;
la columna CENTRO, si existe, también se usa (debe ser uno de los centros de la hoja; sirve el código o el nombre). El resto de columnas (cable, par, nombre, dirección...) se ignora.

Todo o nada: si alguna fila tiene un error no se importa ninguna, y se informa de cada error con su número de fila. Cada fila pasa por las mismas
reglas que la inserción a mano (`obtener_orden` y `asignar_orden`).
"""
import csv
import io
import re
import unicodedata

from django.core.exceptions import ValidationError
from django.db import transaction

from catalogos.models import Centro, TipoMantenimiento, TipoOrden, TipoTrabajo

from .models import OrdenServicio
from .services import asignar_orden, obtener_orden

MAXIMO_FILAS = 500
HORARIO = re.compile(r"\d\s*:\s*\d|\b[ap]\.?m\b", re.IGNORECASE)  # «11:00 – 02:00 PM»: separador de turno en la planificación
COLUMNAS = {  # nombre canónico: alias (ya normalizados)
    "tipo": {"tipo", "tipo de accion", "accion", "categoria"},
    "servicio": {"servicio", "numero de servicio", "numero servicio", "no servicio", "telefono", "servicio telefonico"},
    "tipo_orden": {"tipo de orden", "tipo orden"},
    "orden": {"orden", "numero de orden", "numero orden", "no orden"},
    "mantenimiento": {"mantenimiento", "tipo de mantenimiento", "tipo mantenimiento"},
    "variante": {"variante", "modalidad", "servicio especial"},
    "centro": {"centro"},
    "trabajos": {"trabajos", "trabajo"},
}
TIPOS = {
    "correctivo": "CORRECTIVO", "c": "CORRECTIVO", "preventivo": "PREVENTIVO", "p": "PREVENTIVO",
    "orden de servicio": "ORDEN_SERVICIO", "orden servicio": "ORDEN_SERVICIO", "os": "ORDEN_SERVICIO", "o/s": "ORDEN_SERVICIO",
    "orden de trabajo": "ORDEN_TRABAJO", "orden trabajo": "ORDEN_TRABAJO", "ot": "ORDEN_TRABAJO",
}
VARIANTES = {"": "", "tp": "TP", "telefonia publica": "TP", "nh+": "NHP", "nhp": "NHP", "nauta hogar plus": "NHP", "nh": "NH", "nauta hogar": "NH"}
ENCABEZADOS = ["tipo", "servicio", "tipo de orden", "orden", "mantenimiento", "variante", "centro", "trabajos"]
EJEMPLOS = [
    ["Correctivo", "46-326407", "", "", "", "", "", ""],
    ["Correctivo", "46-318102", "", "", "", "TP", "", ""],
    ["Preventivo", "46-455012", "", "", "MPPE", "", "", ""],
    ["Orden de servicio", "46-300981", "A", "1234", "", "NH", "", ""],
    ["Orden de trabajo", "", "", "567", "", "", "", "Sustitución de poste(s); Sustitución de caja(s) terminal(es)"],
]


def normalizar(texto):
    """Minúsculas, sin tildes y con espacios simples: para comparar nombres de columnas y valores."""
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(texto.lower().replace("_", " ").split())


def _texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():  # Excel guarda 46326407 como número
        return str(int(valor))
    return str(valor).strip()


def _tiene_encabezado(filas):
    """¿Alguna de las primeras filas trae la columna «servicio» o «tipo»?"""
    return any(normalizar(c) in COLUMNAS["servicio"] | COLUMNAS["tipo"] for fila in filas[:15] for c in fila)


def leer_filas(nombre, contenido):
    """[(número de fila del archivo, {columna canónica: texto})] sin las filas vacías. ValidationError si el archivo no sirve."""
    nombre = (nombre or "").lower()
    if nombre.endswith(".csv"):
        try:
            texto = contenido.decode("utf-8-sig")
        except UnicodeDecodeError:
            texto = contenido.decode("latin-1")
        primera = texto.splitlines()[0] if texto.strip() else ""
        delimitador = ";" if primera.count(";") > primera.count(",") else ","
        filas = list(csv.reader(io.StringIO(texto), delimiter=delimitador))
    elif nombre.endswith(".xlsx"):
        from openpyxl import load_workbook
        try:
            libro = load_workbook(io.BytesIO(contenido), data_only=True)
        except Exception as error:  # archivo dañado o que no es un Excel
            raise ValidationError("No se pudo leer el archivo Excel.") from error
        hojas = [[list(f) for f in hoja.iter_rows(values_only=True)] for hoja in libro.worksheets if hoja.sheet_state == "visible"]
        filas = next((h for h in hojas if _tiene_encabezado(h)), hojas[0] if hojas else [])
    elif nombre.endswith(".xls"):
        raise ValidationError("Ese es un Excel antiguo (.xls): ábralo y guárdelo como «Libro de Excel (.xlsx)» o como CSV.")
    else:
        raise ValidationError("El archivo debe ser Excel (.xlsx) o CSV (.csv).")
    if not filas:
        raise ValidationError("El archivo está vacío.")
    columnas, encabezado = {}, 0
    for posicion, candidata in enumerate(filas[:15]):  # el encabezado puede no ser la primera fila (títulos de grupo encima)
        encontradas = {}
        for indice, titulo in enumerate(candidata):
            for canonico, alias in COLUMNAS.items():
                if normalizar(titulo) in alias:
                    encontradas.setdefault(canonico, indice)
        if "tipo" in encontradas or ("servicio" in encontradas and not columnas):
            columnas, encabezado = encontradas, posicion
            if "tipo" in encontradas:
                break
    planificacion = "tipo" not in columnas and "servicio" in columnas
    if "tipo" not in columnas and not planificacion:
        raise ValidationError("Falta la columna «tipo» (Correctivo, Preventivo, Orden de servicio u Orden de trabajo) o, al menos, «servicio».")
    resultado = []
    for numero, fila in enumerate(filas[encabezado + 1:], start=encabezado + 2):
        datos = {c: _texto(fila[i]) if i < len(fila) else "" for c, i in columnas.items()}
        if planificacion:
            servicio = "".join(datos["servicio"].split())  # «46 315207» → «46315207»; «NG» y «ED190069» en dos líneas → «NGED190069»
            if not servicio or HORARIO.search(servicio):
                continue
            datos = {"tipo": "Correctivo", "servicio": servicio, **({"centro": datos["centro"]} if datos.get("centro") else {})}  # la columna CENTRO sí se usa
        if any(datos.values()):
            resultado.append((numero, datos))
    if len(resultado) > MAXIMO_FILAS:
        raise ValidationError(f"El archivo tiene {len(resultado)} filas: el máximo es {MAXIMO_FILAS} por importación.")
    if not resultado:
        raise ValidationError("El archivo no tiene filas con servicios.")
    return resultado


def _buscar(modelo, campo, valor, descripcion):
    objeto = modelo.objects.filter(**{f"{campo}__iexact": valor}).first()
    if objeto is None:
        raise ValidationError(f"{descripcion} «{valor}» no existe en el catálogo.")
    return objeto


def _centro_del_archivo(texto):
    """El centro por su código (NG) o por su nombre (Nueva Gerona), sin importar mayúsculas ni tildes."""
    buscado = normalizar(texto)
    for centro in Centro.objects.all():
        if buscado in (normalizar(centro.codigo), normalizar(centro.nombre)):
            return centro
    raise ValidationError(f"El centro «{texto}» no existe en el catálogo.")


def _crear_accion(hoja, datos, usuario):
    categoria = TIPOS.get(normalizar(datos.get("tipo")))
    if categoria is None:
        raise ValidationError(f"Tipo «{datos.get('tipo')}» no válido: use Correctivo, Preventivo, Orden de servicio u Orden de trabajo.")
    variante = VARIANTES.get(normalizar(datos.get("variante")))
    if variante is None:
        raise ValidationError(f"Variante «{datos.get('variante')}» no válida: use TP, NH+ o NH.")
    tipo_orden = _buscar(TipoOrden, "codigo", datos["tipo_orden"], "El tipo de orden") if datos.get("tipo_orden") else None
    mantenimiento = (_buscar(TipoMantenimiento, "codigo", datos["mantenimiento"], "El tipo de mantenimiento")
                     if datos.get("mantenimiento") else None)
    trabajos = [_buscar(TipoTrabajo, "nombre", n.strip(), "El trabajo") for n in datos.get("trabajos", "").split(";") if n.strip()]
    centro = _centro_del_archivo(datos["centro"]) if datos.get("centro") else None
    orden = obtener_orden(categoria, usuario, numero_servicio=datos.get("servicio", ""), tipo_mantenimiento=mantenimiento, tipo_orden=tipo_orden,
                          numero_orden=datos.get("orden", ""), trabajos=trabajos, variante=variante)
    return asignar_orden(hoja, orden, usuario, centro=centro, trabajos=trabajos or None)


def importar_acciones(hoja, filas, usuario, simular=False):
    """Crea las acciones de `filas` en la hoja. Todo o nada: con algún error (o en simulación) no se guarda nada.

    Devuelve {"filas", "validas", "errores": [{"fila", "mensaje"}], "importadas", "simulacion"}."""
    if hoja.cerrada:
        raise ValidationError("La hoja de ruta está cerrada.")
    errores, validas = [], 0
    with transaction.atomic():
        for numero, datos in filas:
            try:
                with transaction.atomic():  # cada fila en su punto de guardado: un error no estropea las demás
                    _crear_accion(hoja, datos, usuario)
                validas += 1
            except ValidationError as error:
                errores.append({"fila": numero, "mensaje": " ".join(error.messages)})
        if errores or simular:
            transaction.set_rollback(True)
    importadas = 0 if (errores or simular) else validas
    return {"filas": len(filas), "validas": validas, "errores": errores, "importadas": importadas, "simulacion": bool(simular)}


def plantilla_xlsx():
    """Libro de ejemplo con las columnas y una hoja de instrucciones con los códigos válidos."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Acciones"
    hoja.append(ENCABEZADOS)
    for fila in EJEMPLOS:
        hoja.append(fila)
    for celda in hoja[1]:
        celda.font = Font(bold=True)
    for columna, ancho in zip("ABCDEFGH", (20, 16, 14, 12, 16, 10, 10, 60)):
        hoja.column_dimensions[columna].width = ancho
    ayuda = libro.create_sheet("Instrucciones")
    lineas = [
        ["Una fila por servicio. Borre las filas de ejemplo antes de importar."],
        ["tipo", "Correctivo, Preventivo, Orden de servicio u Orden de trabajo (o C, P, OS, OT)."],
        ["servicio", "Número del servicio telefónico (no aplica a las órdenes de trabajo)."],
        ["tipo de orden", "Solo órdenes de servicio: " + ", ".join(TipoOrden.objects.order_by("codigo").values_list("codigo", flat=True))],
        ["orden", "Número de la orden (órdenes de servicio y de trabajo)."],
        ["mantenimiento", "Solo preventivos: " + ", ".join(TipoMantenimiento.objects.filter(activo=True).order_by("codigo").values_list("codigo", flat=True))],
        ["variante", "Opcional. Correctivo: TP (Telefonía Pública) o NH+ (Nauta Hogar Plus). Alta de orden de servicio: NH (Nauta Hogar)."],
        ["centro", "Opcional. Código del centro, si la hoja trabaja en varios: " + ", ".join(Centro.objects.filter(activo=True).order_by("codigo").values_list("codigo", flat=True))],
        ["trabajos", "Solo órdenes de trabajo: nombres de los trabajos separados por «;»."],
    ]
    for linea in lineas:
        ayuda.append(linea)
    ayuda.column_dimensions["A"].width = 16
    ayuda.column_dimensions["B"].width = 110
    memoria = io.BytesIO()
    libro.save(memoria)
    return memoria.getvalue()
