from datetime import date

from django.contrib.auth import authenticate, login, logout
from django.http import HttpResponse
from django.core.exceptions import ValidationError as ErrorDjango
from django.db import transaction
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from catalogos.models import (Brigada, CausaIncidencia, Centro, Clave, Operario, TipoMantenimiento, TipoOrden, TipoTrabajo,
                              Vehiculo)
from operacion.models import Accion, DestinatarioInforme, HojaDeRuta, Incidencia, InformeEnviado, OrdenServicio
from operacion.informes import generar_informe
from operacion.reportes import analisis_de_jefatura, resumen_periodo
from catalogos.models import NormaTiempo, NormaTrabajo
from operacion.services import (asignar_no_visitadas, asignar_orden, asignar_pendientes, obtener_orden, cerrar_hoja, cerrar_sin_ok, certificar_ok,
                                finalizar_incidencia, historial_servicio, iniciar_incidencia, ordenes_no_visitadas,
                                ordenes_pendientes, pasar_a_brigada, resumen_hoja)

from . import serializers as s


# ---------------------------------------------------------------- sesión

def _datos_usuario(usuario):
    return {
        "id": usuario.pk,
        "username": usuario.username,
        "nombre": usuario.get_full_name() or usuario.username,
        "grupos": list(usuario.groups.values_list("name", flat=True)),
        "hoy": timezone.localdate(),  # el día lo decide el servidor (hora de Cuba), no el reloj del equipo del usuario
        "es_superusuario": usuario.is_superuser,
        "es_staff": usuario.is_staff,
        # El acceso al panel de administración es solo para quien gestiona catálogos (no para probadores ni jefes).
        "puede_administrar": usuario.is_staff and (usuario.is_superuser or usuario.has_perm("catalogos.change_clave")),
        "permisos": sorted(usuario.get_all_permissions()),
    }


@method_decorator(ensure_csrf_cookie, name="dispatch")
class SesionView(APIView):
    """GET /api/auth/me/ -> datos del usuario conectado (y entrega la cookie CSRF a la pantalla web)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(_datos_usuario(request.user))


@method_decorator(ensure_csrf_cookie, name="dispatch")
class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        usuario = authenticate(request, username=request.data.get("username"), password=request.data.get("password"))
        if usuario is None or not usuario.is_active:
            return Response({"detail": "Usuario o contraseña incorrectos."}, status=status.HTTP_400_BAD_REQUEST)
        login(request, usuario)
        return Response(_datos_usuario(usuario))


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- catálogos (solo lectura)

class CatalogoViewSet(viewsets.ReadOnlyModelViewSet):
    pagination_class = None  # los catálogos son pequeños: la pantalla los carga completos


class BrigadaViewSet(CatalogoViewSet):
    queryset = Brigada.objects.filter(activa=True)
    serializer_class = s.BrigadaSerializer


class CentroViewSet(CatalogoViewSet):
    queryset = Centro.objects.filter(activo=True)
    serializer_class = s.CentroSerializer


class VehiculoViewSet(CatalogoViewSet):
    queryset = Vehiculo.objects.filter(activo=True)
    serializer_class = s.VehiculoSerializer


class OperarioViewSet(CatalogoViewSet):
    queryset = Operario.objects.filter(activo=True).select_related("brigada")
    serializer_class = s.OperarioSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        brigada = self.request.query_params.get("brigada")
        return qs.filter(brigada_id=brigada) if brigada else qs


class TipoOrdenViewSet(CatalogoViewSet):
    queryset = TipoOrden.objects.all()
    serializer_class = s.TipoOrdenSerializer


class TipoMantenimientoViewSet(CatalogoViewSet):
    queryset = TipoMantenimiento.objects.filter(activo=True)
    serializer_class = s.TipoMantenimientoSerializer


class TipoTrabajoViewSet(CatalogoViewSet):
    queryset = TipoTrabajo.objects.filter(activo=True).prefetch_related("normas")
    serializer_class = s.TipoTrabajoSerializer


class CausaIncidenciaViewSet(CatalogoViewSet):
    queryset = CausaIncidencia.objects.all()
    serializer_class = s.CausaIncidenciaSerializer


class ClaveViewSet(CatalogoViewSet):
    """Por defecto solo claves activas. Filtros: ?grupo=Cable  ?clasificacion=EFECTIVA  ?q=texto  ?todas=1"""

    queryset = Clave.objects.select_related("grupo").prefetch_related("normas")
    serializer_class = s.ClaveSerializer

    def get_queryset(self):
        qs, p = super().get_queryset(), self.request.query_params
        if not p.get("todas"):
            qs = qs.filter(activa=True)
        if p.get("grupo"):
            qs = qs.filter(grupo__nombre__iexact=p["grupo"])
        if p.get("clasificacion"):
            qs = qs.filter(clasificacion=p["clasificacion"])
        if p.get("q"):
            qs = qs.filter(codigo__icontains=p["q"]) | qs.filter(descripcion__icontains=p["q"])
        return qs


# ---------------------------------------------------------------- hojas de ruta

class HojaViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                  mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Filtros: ?fecha=AAAA-MM-DD  ?desde= ?hasta=  ?brigada=  ?centro=  ?cerrada=true|false"""

    queryset = HojaDeRuta.objects.select_related("brigada", "vehiculo").prefetch_related(
        "operarios", "centros", "acciones", "incidencias__causa")
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_serializer_class(self):
        return s.HojaDetalleSerializer if self.action == "retrieve" else s.HojaSerializer

    def get_queryset(self):
        qs, p = super().get_queryset(), self.request.query_params
        if p.get("fecha"):
            qs = qs.filter(fecha=p["fecha"])
        if p.get("desde"):
            qs = qs.filter(fecha__gte=p["desde"])
        if p.get("hasta"):
            qs = qs.filter(fecha__lte=p["hasta"])
        if p.get("brigada"):
            qs = qs.filter(brigada_id=p["brigada"])
        if p.get("centro"):
            qs = qs.filter(centros=p["centro"])
        if p.get("cerrada") in ("true", "false"):
            qs = qs.filter(cerrada=p["cerrada"] == "true")
        return qs

    def perform_create(self, serializer):
        serializer.save(creado_por=self.request.user, modificado_por=self.request.user)

    def perform_update(self, serializer):
        if serializer.instance.cerrada:
            raise ErrorDjango("La hoja de ruta está cerrada y no se puede modificar.")
        serializer.save(modificado_por=self.request.user)

    @action(detail=True, methods=["get"])
    def resumen(self, request, pk=None):
        return Response(resumen_hoja(self.get_object()))

    @action(detail=True, methods=["post"], url_path="incidencias/iniciar")
    def iniciar_incidencia(self, request, pk=None):
        """Arranca el contador de una incidencia (si había otra activa, se detiene)."""
        datos = s.IniciarIncidenciaSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        incidencia = iniciar_incidencia(self.get_object(), datos.validated_data["causa"], request.user,
                                        datos.validated_data["observaciones"])
        return Response(s.IncidenciaSerializer(incidencia).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="incidencias/finalizar")
    def finalizar_incidencia(self, request, pk=None):
        """El operario confirmó el cambio de estado: se detiene el contador."""
        incidencia = finalizar_incidencia(self.get_object(), request.user)
        if incidencia is None:
            raise ErrorDjango("La hoja no tiene ninguna incidencia activa.")
        return Response(s.IncidenciaSerializer(incidencia).data)

    @action(detail=True, methods=["get"])
    def informe(self, request, pk=None):
        """Hoja de ruta con el formato de la hoja original, para imprimir o auditar: ?formato=pdf|xlsx"""
        hoja = self.get_object()
        return _descargar(request, hoja.fecha, solo_hoja=hoja.pk)

    @action(detail=True, methods=["post"])
    def cerrar(self, request, pk=None):
        """Cierra la hoja al finalizar el día: detiene los contadores y deja como NO VISITADOS los servicios sin cerrar."""
        hoja = cerrar_hoja(self.get_object(), request.user)
        resumen = resumen_hoja(hoja)
        return Response({"cerrada": True, "no_visitadas": resumen["no_visitadas"], "resumen": resumen})

    @action(detail=True, methods=["post"], url_path="asignar-pendientes")
    def asignar_pendientes(self, request, pk=None):
        """Trae a la hoja los servicios pendientes que otras brigadas pasaron a la suya (en alguno de sus centros).
        Opcional: {"ordenes": [ids]} para traer solo algunos."""
        ids = request.data.get("ordenes")
        ordenes = list(OrdenServicio.objects.filter(pk__in=ids)) if ids is not None else None
        acciones = asignar_pendientes(self.get_object(), request.user, ordenes)
        return Response(s.AccionSerializer(acciones, many=True).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="asignar-no-visitadas")
    def asignar_no_visitadas(self, request, pk=None):
        """Trae a la hoja los servicios no visitados de días anteriores (misma brigada y alguno de sus centros).
        Opcional: {"ordenes": [ids]} para traer solo algunos."""
        ids = request.data.get("ordenes")
        ordenes = list(OrdenServicio.objects.filter(pk__in=ids)) if ids is not None else None
        acciones = asignar_no_visitadas(self.get_object(), request.user, ordenes)
        return Response(s.AccionSerializer(acciones, many=True).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="acciones")
    def crear_accion(self, request, pk=None):
        """Asigna un trabajo a la hoja. Según el tipo de acción se piden solo los datos que le corresponden:
        correctivo (servicio), preventivo (tipo de mantenimiento + servicio), orden de servicio (tipo de orden + número de
        orden + servicio) u orden de trabajo (número de la orden + trabajos; sin número de servicio).

        Si ya existe una orden sin restablecer con esos datos (p. ej. un pendiente), se reutiliza; si no, se crea una nueva
        (en un correctivo es una reincidencia si la anterior ya estaba restablecida)."""
        hoja = self.get_object()
        if hoja.cerrada:
            raise ErrorDjango("La hoja de ruta está cerrada.")
        datos = s.CrearAccionSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        d, usuario = datos.validated_data, request.user
        with transaction.atomic():
            orden = d.get("orden") or obtener_orden(
                d["categoria"], usuario, numero_servicio=d["numero_servicio"], tipo_mantenimiento=d.get("tipo_mantenimiento"),
                tipo_orden=d.get("tipo_orden"), numero_orden=d["numero_orden"], trabajos=d.get("trabajos"))
            accion = asignar_orden(hoja, orden, usuario, centro=d.get("centro"), trabajos=d.get("trabajos") or None)
            accion.descripcion_trabajo = d["descripcion_trabajo"]
            accion.save(update_fields=["descripcion_trabajo", "modificado_en"])
            if orden.categoria != OrdenServicio.Categoria.ORDEN_TRABAJO:
                accion.claves.set(d.get("claves", []))
        return Response(s.AccionSerializer(accion).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------- acciones

class AccionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Filtros: ?hoja=  ?orden=  ?fecha=AAAA-MM-DD"""

    queryset = Accion.objects.select_related("hoja", "orden__tipo_orden", "pasada_a").prefetch_related("claves__grupo")
    serializer_class = s.AccionSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs, p = super().get_queryset(), self.request.query_params
        if p.get("hoja"):
            qs = qs.filter(hoja_id=p["hoja"])
        if p.get("orden"):
            qs = qs.filter(orden_id=p["orden"])
        if p.get("fecha"):
            qs = qs.filter(hoja__fecha=p["fecha"])
        return qs

    def _respuesta(self, accion):
        accion.refresh_from_db()
        return Response(s.AccionSerializer(accion).data)

    def partial_update(self, request, *args, **kwargs):
        """Mientras no esté cerrada, el probador registra las claves y la descripción del trabajo."""
        accion = self.get_object()
        if accion.hora_fin is not None:
            raise ErrorDjango("La acción ya está cerrada y no se puede modificar.")
        if accion.hoja.cerrada:
            raise ErrorDjango("La hoja de ruta está cerrada.")
        es_ot = accion.orden.categoria == OrdenServicio.Categoria.ORDEN_TRABAJO
        if es_ot and request.data.get("claves"):
            raise ErrorDjango("Una orden de trabajo no lleva claves de cierre: seleccione sus trabajos.")
        if not es_ot and request.data.get("trabajos"):
            raise ErrorDjango("Los trabajos solo corresponden a las órdenes de trabajo.")
        datos = s.ActualizarAccionSerializer(accion, data=request.data, partial=True)
        datos.is_valid(raise_exception=True)
        datos.save(modificado_por=request.user)
        return self._respuesta(accion)

    @action(detail=True, methods=["post"])
    def ok(self, request, pk=None):
        """El probador certificó el trabajo (en un correctivo, hablando con el cliente, cuyo nombre es obligatorio)."""
        datos = s.DarOkSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        certificar_ok(self.get_object(), request.user, datos.validated_data["cliente_contactado"])
        return self._respuesta(self.get_object())

    @action(detail=True, methods=["post"], url_path="pasar-a-brigada")
    def pasar_a_brigada(self, request, pk=None):
        """El servicio sigue afectado y depende de otra brigada (cable, línea, reconstrucción, fibra óptica...)."""
        datos = s.PasarABrigadaSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        pasar_a_brigada(self.get_object(), datos.validated_data["brigada"], request.user)
        return self._respuesta(self.get_object())

    @action(detail=True, methods=["post"], url_path="cerrar-sin-ok")
    def cerrar_sin_ok(self, request, pk=None):
        """Cierra la acción sin OK ni pase a otra brigada (p. ej. casa cerrada). No cuenta como efectiva."""
        cerrar_sin_ok(self.get_object(), request.user)
        return self._respuesta(self.get_object())


# ---------------------------------------------------------------- órdenes de servicio

class OrdenViewSet(viewsets.ReadOnlyModelViewSet):
    """Filtros: ?numero=texto  ?estado=PENDIENTE  ?brigada_pendiente="""

    queryset = OrdenServicio.objects.select_related("tipo_orden", "brigada_pendiente").prefetch_related(
        "acciones__hoja", "acciones__centro")
    serializer_class = s.OrdenSerializer

    def get_queryset(self):
        qs, p = super().get_queryset(), self.request.query_params
        if p.get("numero"):
            qs = qs.filter(numero_servicio__icontains=p["numero"])
        if p.get("estado"):
            qs = qs.filter(estado=p["estado"])
        if p.get("brigada_pendiente"):
            qs = qs.filter(brigada_pendiente_id=p["brigada_pendiente"])
        return qs

    @action(detail=False, methods=["get"])
    def pendientes(self, request):
        """Servicios pendientes que deben asignarse a una hoja de la brigada indicada: ?brigada=<id>&centro=<id> (centro se puede repetir)."""
        brigada = Brigada.objects.filter(pk=request.query_params.get("brigada")).first()
        if brigada is None:
            raise ErrorDjango("Indique la brigada: ?brigada=<id>")
        ids = request.query_params.getlist("centro")
        qs = ordenes_pendientes(brigada, list(Centro.objects.filter(pk__in=ids)) if ids else None).select_related("tipo_orden", "brigada_pendiente").prefetch_related("acciones__hoja", "acciones__centro")
        return Response(s.OrdenSerializer(qs, many=True).data)

    @action(detail=False, methods=["get"], url_path="no-visitadas")
    def no_visitadas(self, request):
        """Servicios que la brigada no visitó en días anteriores: ?brigada=<id>&centro=<id> (centro se puede repetir)."""
        brigada = Brigada.objects.filter(pk=request.query_params.get("brigada")).first()
        if brigada is None:
            raise ErrorDjango("Indique la brigada: ?brigada=<id>")
        ids = request.query_params.getlist("centro")
        centros = list(Centro.objects.filter(pk__in=ids)) if ids else None
        qs = ordenes_no_visitadas(brigada, centros).select_related("tipo_orden", "brigada_pendiente").prefetch_related("acciones__hoja", "acciones__centro")
        return Response(s.OrdenSerializer(qs, many=True).data)

    @action(detail=False, methods=["get"])
    def historial(self, request):
        """Seguimiento y reincidencias de un servicio: ?numero=<número exacto>.
        Devuelve cada acción con los operarios que la trabajaron."""
        numero = request.query_params.get("numero", "").strip()
        if not numero:
            raise ErrorDjango("Indique el número de servicio: ?numero=<número>")
        acciones = list(historial_servicio(numero))
        ordenes = {a.orden_id for a in acciones}
        return Response({"numero_servicio": numero, "ordenes": len(ordenes), "acciones": len(acciones),
                         "reincidencia": len(ordenes) > 1,
                         "historial": s.HistorialSerializer(acciones, many=True).data})


# ---------------------------------------------------------------- resúmenes

class ResumenView(APIView):
    """GET /api/resumen/?periodo=dia|mes|anio&fecha=AAAA-MM-DD[&brigada=<id>][&centro=<id>]

    `fecha` puede ser cualquier día del período (por defecto, hoy). Devuelve totales, indicadores por brigada,
    centro y operario (productividad individual), el detalle por día (mes) o por mes (año) y los listados de
    servicios pasados a otra brigada, no visitados y reincidentes."""

    queryset = HojaDeRuta.objects.none()  # los permisos salen de este modelo: hay que poder ver hojas de ruta

    def get(self, request):
        p = request.query_params
        periodo = p.get("periodo", "dia")
        if periodo not in ("dia", "mes", "anio"):
            raise ErrorDjango("El período debe ser dia, mes o anio.")
        try:
            fecha = date.fromisoformat(p["fecha"]) if p.get("fecha") else timezone.localdate()
        except ValueError:
            raise ErrorDjango("Fecha inválida: use el formato AAAA-MM-DD.")
        return Response(resumen_periodo(periodo, fecha, brigada=p.get("brigada") or None, centro=p.get("centro") or None))


# ---------------------------------------------------------------- informes descargables

def _descargar(request, fecha, **filtros):
    formato = request.query_params.get("formato", "pdf")
    try:
        contenido, tipo, nombre = generar_informe(fecha, formato, usuario=request.user, **filtros)
    except ValueError as error:
        raise ErrorDjango(str(error))
    # el PDF se abre en el navegador (para imprimir); el Excel se descarga
    disposicion = "inline" if formato == "pdf" else "attachment"
    return HttpResponse(contenido, content_type=tipo, headers={"Content-Disposition": f'{disposicion}; filename="{nombre}"'})


class InformeDiarioView(APIView):
    """GET /api/informe-diario/?fecha=AAAA-MM-DD&formato=pdf|xlsx[&brigada=][&centro=]

    El resumen del día y todas las hojas de ruta, cada una con el formato de la hoja original (auditable)."""

    queryset = HojaDeRuta.objects.none()

    def get(self, request):
        p = request.query_params
        try:
            fecha = date.fromisoformat(p["fecha"]) if p.get("fecha") else timezone.localdate()
        except ValueError:
            raise ErrorDjango("Fecha inválida: use el formato AAAA-MM-DD.")
        return _descargar(request, fecha, brigada=p.get("brigada") or None, centro=p.get("centro") or None)


# ---------------------------------------------------------------- pantalla de inicio

class InicioView(APIView):
    """GET /api/inicio/ — lo primero que ve cada usuario: la situación de hoy y lo que requiere su atención."""

    queryset = HojaDeRuta.objects.none()

    def get(self, request):
        hoy = timezone.localdate()
        ahora = timezone.now()
        dia = resumen_periodo("dia", hoy, ahora=ahora)
        mes = resumen_periodo("mes", hoy, ahora=ahora)["totales"]

        # hojas de días anteriores que nadie cerró: sus servicios sin cerrar no han pasado a "no visitados"
        abiertas = [{"id": h.pk, "fecha": h.fecha, "etiqueta": f"{h.etiqueta_centros} · {h.brigada.nombre}",
                     "en_curso": h.acciones.filter(hora_fin__isnull=True, no_visitada=False).count()}
                    for h in HojaDeRuta.objects.filter(cerrada=False, fecha__lt=hoy).select_related("brigada")
                    .prefetch_related("centros").order_by("fecha")[:50]]
        incidencias = [{"hoja": i.hoja_id, "etiqueta": f"{i.hoja.etiqueta_centros} · {i.hoja.brigada.nombre}", "causa": str(i.causa),
                        "desde": i.inicio, "minutos": i.minutos(hasta=ahora)}
                       for i in Incidencia.objects.filter(fin__isnull=True, hoja__cerrada=False)
                       .select_related("causa", "hoja__brigada").prefetch_related("hoja__centros")]
        brigadas = list(Brigada.objects.filter(activa=True))
        datos = {
            "fecha": hoy,
            "hoy": dia["totales"],
            "mes": {k: mes[k] for k in ("hojas", "acciones", "ok", "efectividad_pct", "productividad_pct", "ocupacion_pct")},
            "hojas_hoy": dia["hojas"],
            "hojas_abiertas_anteriores": abiertas,
            "incidencias_activas": incidencias,
            "no_visitadas": [{"brigada_id": b.pk, "brigada": b.nombre, "cantidad": n}
                             for b in brigadas if (n := ordenes_no_visitadas(b).count())],
            "pendientes": [{"brigada_id": b.pk, "brigada": b.nombre, "cantidad": n}
                           for b in brigadas if (n := ordenes_pendientes(b).count())],
            "catalogos": None,
        }
        if request.user.is_staff and (request.user.is_superuser or request.user.has_perm("catalogos.change_clave")):
            datos["catalogos"] = {
                "claves_por_revisar": Clave.objects.filter(revisar=True, activa=True).count(),
                "claves_sin_norma": Clave.objects.filter(activa=True).exclude(
                    pk__in=NormaTiempo.objects.values("clave_id")).count(),
                "trabajos_sin_norma": TipoTrabajo.objects.filter(activo=True).exclude(
                    pk__in=NormaTrabajo.objects.values("tipo_trabajo_id")).count(),
                "informe_diario": None,
            }
            if request.user.is_superuser:  # la lista de destinatarios y el envío son cosa del administrador
                ultimo = InformeEnviado.objects.exclude(estado=InformeEnviado.Estado.OMITIDO).first()
                datos["catalogos"]["informe_diario"] = {
                    "destinatarios": DestinatarioInforme.objects.filter(activo=True).count(),
                    "ultimo": {"fecha": ultimo.fecha, "estado": ultimo.estado, "detalle": ultimo.detalle} if ultimo else None,
                }
        return Response(datos)


class AnalisisView(APIView):
    """GET /api/analisis/?periodo=anterior|mes|anio — para Inicio (jefes y especialistas): tiempo perdido por causa de
    incidencia, y los operarios y vehículos más productivos de la jornada anterior, del mes o del año."""

    queryset = HojaDeRuta.objects.none()

    def get(self, request):
        periodo = request.query_params.get("periodo", "anterior")
        if periodo not in ("anterior", "mes", "anio"):
            raise ErrorDjango("El período debe ser anterior, mes o anio.")
        return Response(analisis_de_jefatura(timezone.localdate(), periodo))
