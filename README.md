# Mesa de Pruebas — Fase 1: catálogos y registro

## Puesta en marcha
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt      # solo Django (SQLite). Para PostgreSQL: requirements-postgres.txt
docker compose up -d                 # PostgreSQL (o exporte POSTGRES_* hacia su servidor)
export $(cat .env.example | xargs)   # copie a .env y cambie las claves
python manage.py migrate
python manage.py cargar_inicial      # brigadas, causas, 180 claves con normas, roles
python manage.py createsuperuser
python manage.py crear_demo         # hoja de ejemplo completa (se puede repetir)
python manage.py runserver           # http://localhost:8000/admin
python manage.py test                # la suite de pruebas de las reglas de negocio
```
Sin `POSTGRES_DB` en el entorno usa SQLite (solo para pruebas rápidas).

## Roles (grupos creados por `cargar_inicial`)
- **Probador**: crea hojas de ruta, órdenes y acciones, da el OK. Solo consulta catálogos. No borra.
- **Especialista**: gestiona catálogos y normas.
- **Jefe**: solo consulta.

## API REST (`/api/`) — fase 2
Misma sesión que la administración: quien entró a `/admin` ya puede abrir `http://127.0.0.1:8000/api/` en el navegador.
Los permisos salen de los roles: **Probador** registra, **Jefe** y **Especialista** consultan. Escribir desde una
pantalla web exige el token CSRF (cookie `csrftoken` -> cabecera `X-CSRFToken`).

| Método y ruta | Qué hace |
|---|---|
| `POST /api/auth/login/` · `POST /api/auth/logout/` · `GET /api/auth/me/` | Sesión y datos del usuario |
| `GET /api/brigadas/ centros/ vehiculos/ operarios/ tipos-orden/ causas-incidencia/` | Catálogos |
| `GET /api/claves/?grupo=&q=&clasificacion=` | Claves activas con su norma vigente |
| `GET /api/hojas/?fecha=&brigada=&centro=&cerrada=` · `POST /api/hojas/` | Listar / crear hojas de ruta |
| `GET /api/hojas/{id}/` | Hoja con acciones, incidencias y resumen de indicadores |
| `POST /api/hojas/{id}/acciones/` | Asignar un servicio a la hoja (`numero_servicio`, o `orden`) |
| `PATCH /api/acciones/{id}/` | Registrar claves y descripción mientras la acción está abierta |
| `POST /api/acciones/{id}/ok/` · `pasar-a-brigada/` · `cerrar-sin-ok/` | Cierre de la acción (genera hora de fin y tiempo real) |
| `POST /api/hojas/{id}/incidencias/iniciar/` · `finalizar/` | Contador de incidencias |
| `POST /api/hojas/{id}/cerrar/` | Cierre de la hoja: lo sin cerrar pasa a no visitado |
| `POST /api/hojas/{id}/asignar-no-visitadas/` | Trae a la hoja los no visitados de su brigada y centro |
| `GET /api/ordenes/no-visitadas/?brigada=&centro=` | Servicios que quedaron sin visitar en días anteriores |
| `GET /api/ordenes/pendientes/?brigada=` | Pendientes para asignar a una hoja de esa brigada |
| `GET /api/ordenes/historial/?numero=` | Seguimiento y reincidencias, con los operarios de cada acción |

Regla al asignar un servicio: si su número ya tiene una orden sin restablecer (p. ej. un pendiente) se reutiliza;
si estaba restablecida se crea una orden nueva (reincidencia).

## Pantalla web (React) — fase 3
Carpeta `frontend/`. Requiere Node.js 20.19 o superior (o 22.12+).
```bash
# Terminal 1 (con .venv activado): el servidor Django
python manage.py runserver
# Terminal 2: la pantalla web
cd frontend
npm install        # solo la primera vez
npm run dev        # abre http://localhost:5173
```
- Los probadores entran por `http://localhost:5173` con el usuario que les creó el administrador.
- Funciones: hojas del día, crear hoja, asignar servicios (y pendientes), registrar claves, dar OK con el cliente,
  pasar a otra brigada, cerrar sin OK, historial/reincidencias, incidencias con contador y cierre del día.
- El Jefe y el Especialista ven la misma pantalla en modo consulta (sin botones de registro).
- Para producción se compila con `npm run build` (carpeta `frontend/dist`); su despliegue se verá en la fase final.

## Resúmenes (diario, mensual y anual)
Sección **Resumen** de la pantalla web, o `GET /api/resumen/?periodo=dia|mes|anio&fecha=AAAA-MM-DD[&brigada=][&centro=]`.
Muestra totales, indicadores por brigada, centro y **operario (productividad individual)**, el detalle por día (mes) o por
mes (año) con gráfico, el detalle por hoja (día), y los listados de servicios **pasados a otra brigada**, **no visitados**
(con su situación actual) y **reincidencias** (con los operarios que los trabajaron). Botón "Imprimir" (para papel o PDF
desde el navegador). Un año con 65 000 acciones se calcula en menos de 2 segundos.

Definiciones (las mismas que el resumen de cada hoja; las pruebas verifican que coinciden):
- Efectividad = acciones con OK / acciones atendidas (las no visitadas no cuentan).
- Productividad = minutos normados de las acciones con OK / minutos reales consumidos (ya sin incidencias).
- Tiempo disponible = (420 min − incidencias que descuentan) × operarios de cada hoja; Ocupación = tiempo real / disponible.
- La productividad es de la hoja completa: cada operario recibe la de las hojas en que participó.
- Reincidencia = un servicio con más de una orden dentro del período.

## Tipos de acción
Al asignar un trabajo a la hoja se elige el tipo, y **solo se activan los campos que le corresponden**:

| Tipo | Se introduce |
|---|---|
| Correctivo | Número del servicio telefónico |
| Preventivo | Tipo de mantenimiento (MPPI, MPPE, MPI) + número del servicio |
| Orden de servicio | Tipo de orden (A, TA, ...) + número de orden + número del servicio |
| Orden de trabajo | Número de la orden de trabajo + trabajos (sin número de servicio) |

- Los **trabajos** de las órdenes de trabajo (Sustitución de poste(s), de caja(s) terminal(es), ...) los crean el
  administrador y los especialistas en el catálogo, cada uno con su **norma de tiempo** (con vigencia). La norma de una
  orden de trabajo es la de su trabajo de mayor norma.
- Para cerrar: un correctivo, preventivo u orden de servicio necesita claves de cierre; una orden de trabajo, sus trabajos.
  El **cliente** que certificó es obligatorio solo en los correctivos; en los demás es opcional.
- La reincidencia se calcula solo con correctivos.
- La API rechaza los campos que no corresponden al tipo (`POST /api/hojas/{id}/acciones/` con `categoria`).

## Pantalla de Inicio
Es lo primero que ve cada usuario al entrar (`GET /api/inicio/`): la situación de hoy y **lo que requiere su atención**
- hojas de días anteriores que nadie cerró (sus servicios sin cerrar aún no han pasado a "no visitados"),
- incidencias con el contador activo,
- servicios no visitados y pendientes por brigada (con acceso directo a crear la hoja de ruta; al crear una hoja el formulario
  ofrece traerlos solos, por brigada y centro),
- y, solo para administradores y especialistas, claves "por revisar" y claves activas sin norma de tiempo.
- Si no hay nada: "Inicio de jornada sin tareas pendientes".
- **Análisis** (jefes, especialistas y administración): tiempo perdido por causa de incidencia y operarios y vehículos más
  productivos de la jornada anterior, del mes y del año (`GET /api/analisis/?periodo=anterior|mes|anio`).
- **Aviso al salir**: quien registra hojas recibe un aviso si intenta salir (o cerrar la pestaña) con hojas sin cerrar.

## Informes en PDF y Excel (auditables)
Con el **formato de la hoja de ruta original** (recuadro "HOJA DE RUTA"; **Centro: x-x**, **Operarios: x-x**, chapa y fecha;
solo las filas de las acciones del día, con Trabajo, Descripción del Trabajo —número de servicio o de orden y claves de cierre—,
Hora y Cliente). Se agregan, aparte, las columnas de control (Resultado, tiempo real y
norma) y el pie de elaboración y cierre.
- **Una hoja**: botones PDF y Excel en la hoja (`GET /api/hojas/{id}/informe/?formato=pdf|xlsx`).
- **El día completo**: en Resumen (día) y en Inicio (`GET /api/informe-diario/?fecha=&formato=pdf|xlsx[&brigada=][&centro=]`):
  primera página con el resumen del día y una página por hoja de ruta.
- El Excel trae tres hojas: *Resumen*, *Hojas de ruta* (bloques de 5 columnas lado a lado, igual que el original) y
  *Auditoría* (una fila por servicio, con filtros).
- El PDF se abre en el navegador (para imprimir); el Excel se descarga.
- Todo sale de `operacion/informes.py` (`generar_informe`), que será también lo que use el envío automático por correo.
- Las pruebas que leen el texto del PDF usan `pdfplumber` (opcional: `pip install pdfplumber`); sin él se omiten.

## Identidad visual
Logotipo de la aplicación: `frontend/public/logo-udat.svg` (una U con marca de verificación; otras propuestas en `logos/`).
Se usa en la pantalla de entrada, la pestaña del navegador y el encabezado de los informes.

## Pendiente (en este orden)
1. Envío automático del informe diario por correo (servidor smtp.etecsa.cu) a un grupo definido por el administrador, con
   corte a las 16:00 aunque haya hojas abiertas, y copia de lo enviado para auditoría.
2. PostgreSQL (crear la base y probar las migraciones).
3. Autenticación con LDAP.
(Los Excel históricos no se importan: se empieza de cero.)

## Varios centros por hoja
Un vehículo puede trabajar en **varios centros en la misma hoja de ruta** (se eligen con casillas al crearla; el título
muestra p. ej. "FI + NG"). Cada servicio indica su centro:
- Hoja de un solo centro: el servicio toma ese centro solo.
- Hoja de varios centros: se elige en "Centro del servicio" (la API exige `centro` si hay más de uno).
- Un servicio que ya estuvo en un centro de la hoja (no visitado o pendiente) vuelve a él sin preguntar.
- Los **no visitados** se ofrecen a hojas de la misma brigada que incluyan el centro donde estaban.
- El resumen **por centro** reparte los servicios según su centro; no muestra tiempo disponible ni ocupación (el tiempo
  disponible es de la hoja completa y no se puede repartir entre centros). El filtro por centro trae las hojas que
  trabajaron en él.

## Reglas de la hoja de ruta (actualizadas)
- **Un operario no puede estar en más de una hoja de ruta el mismo día.** Se controla en la pantalla (los ocupados
  aparecen bloqueados), en la API, en la administración y en el modelo. Si tiene datos de prueba anteriores a esta regla:
  `python manage.py operarios_duplicados` lista los casos para corregirlos en `/admin`.
- **Al cerrar la hoja**, los servicios que no se cerraron pasan a **NO VISITADOS** (no cuentan en la efectividad):
  - El resumen de la hoja y del día muestra las **pasadas a otra brigada** (con su brigada) y las **no visitadas**.
  - Quedan guardados: al crear una hoja nueva de la misma **brigada y centro** se ofrecen y se traen solos
    (opción marcada por defecto en el formulario, o desde la hoja con "Asignar").
  - Si el servicio era un pendiente de otra brigada y esa brigada no llegó, sigue pendiente para ella.

## Roles y acceso a la administración
- La pantalla web (`http://localhost:5173`) es para Probador, Jefe y Especialista. Solo quien gestiona catálogos
  (Especialista y administrador) ve el enlace "Administración".
- Recomendado: **no marque "Es staff"** a probadores ni jefes (así tampoco pueden abrir `/admin` escribiendo la
  dirección). "Es staff" solo para especialistas y administradores.

## Identidad visual
Fondo en grises suaves (página `#dfe3e9`, tarjetas `#eff1f5`, campos `#f8f9fb`; se cambian en la parte superior de
`frontend/src/estilos.css`). Colores corporativos azul `#050752` y verde `#059E1A` (para texto y botones con letra blanca se usa `#047A16`,
un verde más oscuro que cumple el contraste de lectura), logotipo de ETECSA y título "Unidad de Asistencia Técnica · UDAT"
(`frontend/public/logo-etecsa.png`, `frontend/src/estilos.css`).

## Reglas implementadas (`operacion/services.py`)
- Una acción puede tener varias claves; **la norma de tiempo es la de la clave mayor**.
- **Efectiva = acción con OK del probador** (con el cliente contactado). Sin OK no cuenta, aunque alguna clave sea efectiva.
- **Tiempo real** = hora de fin de la acción − hora de fin de la acción anterior de la hoja. La primera usa la
  `hora_inicio` de la hoja. La hora de fin se genera sola al: `certificar_ok`, `pasar_a_brigada` o `cerrar_sin_ok`.
- **Pasar a otra brigada**: el probador elige la brigada en cada caso; la orden queda pendiente para esa brigada.
- Normas por clave y tipo de orden, con vigencia: cambiar una norma no altera meses anteriores.
- `resumen_hoja`: efectividad (% con OK), productividad (normado efectivo / real), ocupación (real / 420 × operarios).
- `historial_servicio`: acciones previas sobre un servicio y qué operarios las hicieron (reincidencias, calidad).

## Incidencias (contador)
- Claves oficiales: 100 Lluvia, 101 Traslado de personal, 102 Esperando materiales, 105 Esperando por probador,
  106 Problemas con el transporte, 107 Realizando actividades comerciales, 108 Otras causas, 110 Autorizado por el jefe.
- En la hoja de ruta, la sección **Incidencias**: al elegir una causa y guardar, **arranca el contador**.
- Se detiene con la acción "Finalizar la incidencia en curso" (el operario confirmó el cambio de estado), al iniciar
  otra incidencia, o al **cerrar la hoja** al final del día (acción "Cerrar la hoja de ruta").
- Las incidencias con `descuenta_tiempo` (todas por defecto; se cambia en el catálogo de causas) se restan del
  tiempo real de las acciones y del tiempo disponible: la productividad y la ocupación son reales.
- Una hoja cerrada solo la puede modificar el superusuario.

## Centros
Cada centro tiene código (NG Nueva Gerona, FI La Fé, FO La Reforma). El administrador agrega el resto.

## Catálogos: crear, modificar, eliminar
- **Claves** y **Normas de tiempo**: Administración -> Claves (las normas aparecen al final de cada clave) o
  Normas de tiempo. Una clave ya usada en acciones no se elimina (se desmarca "activa") para no alterar el historial.
- Para cambiar una norma sin alterar el pasado: ponga fecha fin a la vigente y cree otra con su fecha de inicio.

## Claves (180 → 177 en el catálogo)
- No efectivas (definidas por el negocio): 01, 02, 14-P, 21, 22, 23, 24, 25, 27, 29, 36, 36-V, 36D-TXD, 37, 38, 39, 70.
- Eliminadas del catálogo: 09-R, 39-W, 63-X. Repetidas (11DW-TXD, 1DMC-TXD, 3DS-TXD): solo el grupo Datos.
- Marcadas "revisar" (el PDF las daba como no efectivas y el negocio no las incluyó): 07-EP, 07-IP, 08, 09, 35-D.
- La jornada empieza a las 08:00 (`HORA_INICIO_JORNADA` en settings): base del tiempo real de la primera acción.
- Compatible con Python 3.12 a 3.14 (Django 5.2.8 o superior).
