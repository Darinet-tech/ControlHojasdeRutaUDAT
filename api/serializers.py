from collections import Counter

from django.core.exceptions import ValidationError as ErrorDjango
from django.utils import timezone
from rest_framework import serializers

from catalogos.models import (Brigada, CausaIncidencia, Centro, Clave, NormaTrabajo, Operario, TipoMantenimiento, TipoOrden,
                              TipoTrabajo, Vehiculo)
from operacion.models import Accion, HojaDeRuta, Incidencia, OrdenServicio
from operacion.services import norma_accion, resumen_hoja, sugerir_ok, validar_operarios_libres


# ---------------------------------------------------------------- catálogos (solo lectura)

class BrigadaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brigada
        fields = ["id", "nombre", "activa"]


class CentroSerializer(serializers.ModelSerializer):
    class Meta:
        model = Centro
        fields = ["id", "codigo", "nombre", "activo"]


class VehiculoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehiculo
        fields = ["id", "chapa", "descripcion", "activo"]


class OperarioSerializer(serializers.ModelSerializer):
    brigada_nombre = serializers.CharField(source="brigada.nombre", read_only=True)

    class Meta:
        model = Operario
        fields = ["id", "clave", "nombre", "brigada", "brigada_nombre", "activo"]


class TipoOrdenSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoOrden
        fields = ["id", "codigo", "nombre"]


class TipoMantenimientoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoMantenimiento
        fields = ["id", "codigo", "nombre"]


class TipoTrabajoSerializer(serializers.ModelSerializer):
    norma_min = serializers.SerializerMethodField(help_text="Norma vigente hoy (minutos).")

    class Meta:
        model = TipoTrabajo
        fields = ["id", "nombre", "norma_min", "activo"]

    def get_norma_min(self, tipo):
        hoy = timezone.localdate()
        vigentes = [n for n in tipo.normas.all() if n.vigente_desde <= hoy and (n.vigente_hasta is None or n.vigente_hasta >= hoy)]
        return max(vigentes, key=lambda n: n.vigente_desde).minutos if vigentes else None


class CausaIncidenciaSerializer(serializers.ModelSerializer):
    class Meta:
        model = CausaIncidencia
        fields = ["id", "codigo", "nombre", "descuenta_tiempo"]


class ClaveSerializer(serializers.ModelSerializer):
    grupo = serializers.CharField(source="grupo.nombre", read_only=True)
    norma_min = serializers.SerializerMethodField(help_text="Norma general vigente hoy (minutos).")

    class Meta:
        model = Clave
        fields = ["id", "codigo", "grupo", "descripcion", "clasificacion", "ambito", "norma_min", "activa"]

    def get_norma_min(self, clave):
        hoy = timezone.localdate()
        generales = [n for n in clave.normas.all() if n.tipo_orden_id is None and n.vigente_desde <= hoy
                     and (n.vigente_hasta is None or n.vigente_hasta >= hoy)]
        return max(generales, key=lambda n: n.vigente_desde).minutos if generales else None


# ---------------------------------------------------------------- operación

class IncidenciaSerializer(serializers.ModelSerializer):
    causa_codigo = serializers.CharField(source="causa.codigo", read_only=True)
    causa_nombre = serializers.CharField(source="causa.nombre", read_only=True)
    minutos = serializers.SerializerMethodField()
    activa = serializers.BooleanField(read_only=True)

    class Meta:
        model = Incidencia
        fields = ["id", "causa", "causa_codigo", "causa_nombre", "inicio", "fin", "activa", "minutos", "observaciones"]

    def get_minutos(self, incidencia):
        return incidencia.minutos()


class IniciarIncidenciaSerializer(serializers.Serializer):
    causa = serializers.PrimaryKeyRelatedField(queryset=CausaIncidencia.objects.all())
    observaciones = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class AccionSerializer(serializers.ModelSerializer):
    numero_servicio = serializers.CharField(source="orden.numero_servicio", read_only=True)
    etiqueta = serializers.CharField(source="orden.etiqueta", read_only=True)
    categoria = serializers.CharField(source="orden.categoria", read_only=True)
    categoria_texto = serializers.CharField(source="orden.get_categoria_display", read_only=True)
    tipo_mantenimiento = serializers.CharField(source="orden.tipo_mantenimiento.codigo", read_only=True, default=None)
    numero_orden = serializers.CharField(source="orden.numero_orden", read_only=True)
    trabajos = TipoTrabajoSerializer(many=True, read_only=True)
    tipo_orden = serializers.CharField(source="orden.tipo_orden.codigo", read_only=True, default=None)
    centro_codigo = serializers.CharField(source="centro.codigo", read_only=True, default=None)
    estado_orden = serializers.CharField(source="orden.estado", read_only=True)
    claves = ClaveSerializer(many=True, read_only=True)
    pasada_a_nombre = serializers.CharField(source="pasada_a.nombre", read_only=True, default=None)
    norma_min = serializers.SerializerMethodField(help_text="Norma de la clave mayor (minutos).")
    sugerencia_ok = serializers.SerializerMethodField()
    estado = serializers.SerializerMethodField()

    class Meta:
        model = Accion
        fields = ["id", "hoja", "orden", "numero", "etiqueta", "categoria", "categoria_texto", "numero_servicio", "tipo_mantenimiento",
                  "tipo_orden", "numero_orden", "trabajos", "centro", "centro_codigo", "estado_orden", "claves",
                  "descripcion_trabajo", "observaciones", "estado", "ok", "cliente_contactado", "pasada_a",
                  "pasada_a_nombre", "hora_fin", "tiempo_real_min", "norma_min", "sugerencia_ok"]

    def get_norma_min(self, accion):
        return norma_accion(accion)

    def get_sugerencia_ok(self, accion):
        return sugerir_ok(accion) if accion.estado == "EN_CURSO" else None

    def get_estado(self, accion):
        return accion.estado


class ActualizarAccionSerializer(serializers.ModelSerializer):
    """Mientras la acción no esté cerrada, el probador completa sus claves (o los trabajos, en una orden de trabajo)."""

    claves = serializers.PrimaryKeyRelatedField(many=True, queryset=Clave.objects.filter(activa=True), required=False)
    trabajos = serializers.PrimaryKeyRelatedField(many=True, queryset=TipoTrabajo.objects.filter(activo=True), required=False)

    class Meta:
        model = Accion
        fields = ["claves", "trabajos", "descripcion_trabajo", "observaciones"]


class CrearAccionSerializer(serializers.Serializer):
    """Asigna un trabajo a la hoja. Se indica el tipo de acción y SOLO los datos que le corresponden (se validan en
    `operacion.services.obtener_orden`):

    - correctivo: numero_servicio
    - preventivo: tipo_mantenimiento + numero_servicio
    - orden_servicio: tipo_orden + numero_orden + numero_servicio
    - orden_trabajo: numero_orden + trabajos (no lleva número de servicio)

    O bien `orden`: una orden que ya existe (un pendiente o un no visitado)."""

    orden = serializers.PrimaryKeyRelatedField(queryset=OrdenServicio.objects.all(), required=False)
    categoria = serializers.ChoiceField(choices=OrdenServicio.Categoria.choices, default=OrdenServicio.Categoria.CORRECTIVO)
    numero_servicio = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    tipo_mantenimiento = serializers.PrimaryKeyRelatedField(queryset=TipoMantenimiento.objects.filter(activo=True), required=False, allow_null=True)
    tipo_orden = serializers.PrimaryKeyRelatedField(queryset=TipoOrden.objects.all(), required=False, allow_null=True)
    numero_orden = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    trabajos = serializers.PrimaryKeyRelatedField(many=True, queryset=TipoTrabajo.objects.filter(activo=True), required=False)
    centro = serializers.PrimaryKeyRelatedField(queryset=Centro.objects.all(), required=False, allow_null=True,
                                                help_text="Obligatorio si la hoja trabaja en varios centros.")
    claves = serializers.PrimaryKeyRelatedField(many=True, queryset=Clave.objects.filter(activa=True), required=False)
    descripcion_trabajo = serializers.CharField(required=False, allow_blank=True, default="")


class PasarABrigadaSerializer(serializers.Serializer):
    brigada = serializers.PrimaryKeyRelatedField(queryset=Brigada.objects.filter(activa=True))


class DarOkSerializer(serializers.Serializer):
    cliente_contactado = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")  # obligatorio solo en correctivos


class HojaSerializer(serializers.ModelSerializer):
    brigada_nombre = serializers.CharField(source="brigada.nombre", read_only=True)
    centros_codigos = serializers.SerializerMethodField()
    centros_etiqueta = serializers.CharField(source="etiqueta_centros", read_only=True)
    vehiculo_chapa = serializers.CharField(source="vehiculo.chapa", read_only=True, default=None)
    operarios_nombres = serializers.SerializerMethodField()
    cantidad_acciones = serializers.SerializerMethodField()
    resultados = serializers.SerializerMethodField()
    incidencia_activa = serializers.SerializerMethodField()

    class Meta:
        model = HojaDeRuta
        fields = ["id", "fecha", "brigada", "brigada_nombre", "centros", "centros_codigos", "centros_etiqueta", "vehiculo",
                  "vehiculo_chapa", "operarios", "operarios_nombres", "hora_inicio", "observaciones", "cerrada",
                  "cerrada_en", "cantidad_acciones", "resultados", "incidencia_activa"]
        read_only_fields = ["cerrada", "cerrada_en"]
        extra_kwargs = {
            "centros": {"error_messages": {"empty": "Indique al menos un centro."}},
            "operarios": {"error_messages": {"empty": "La hoja de ruta necesita al menos un operario."}},
        }

    def get_centros_codigos(self, hoja):
        return sorted(c.codigo for c in hoja.centros.all())

    def validate_centros(self, centros):
        if not centros:
            raise serializers.ValidationError("Indique al menos un centro.")
        inactivos = [c.codigo for c in centros if not c.activo]
        if inactivos:
            raise serializers.ValidationError(f"Centros inactivos: {', '.join(inactivos)}")
        return centros

    def get_operarios_nombres(self, hoja):
        return [o.nombre for o in hoja.operarios.all()]

    def get_cantidad_acciones(self, hoja):
        return len(hoja.acciones.all())

    def get_resultados(self, hoja):
        cuenta = Counter(a.estado for a in hoja.acciones.all())
        return {"ok": cuenta["OK"], "sin_ok": cuenta["SIN_OK"], "pasadas": cuenta["PASADA_A_BRIGADA"],
                "no_visitadas": cuenta["NO_VISITADA"], "en_curso": cuenta["EN_CURSO"]}

    def get_incidencia_activa(self, hoja):
        activa = next((i for i in hoja.incidencias.all() if i.fin is None), None)
        return str(activa.causa) if activa else None

    def validate_operarios(self, operarios):
        if not operarios:
            raise serializers.ValidationError("La hoja de ruta necesita al menos un operario.")
        inactivos = [o.clave for o in operarios if not o.activo]
        if inactivos:
            raise serializers.ValidationError(f"Operarios inactivos: {', '.join(inactivos)}")
        return operarios

    def validate(self, datos):
        """Un operario no puede estar en más de una hoja de ruta el mismo día."""
        hoja = self.instance
        if "operarios" in datos or "fecha" in datos:
            fecha = datos.get("fecha", hoja.fecha if hoja else None)
            operarios = datos.get("operarios", list(hoja.operarios.all()) if hoja else [])
            try:
                validar_operarios_libres(fecha, operarios, excluir_hoja=hoja)
            except ErrorDjango as error:
                raise serializers.ValidationError({"operarios": error.messages})
        return datos


class HojaDetalleSerializer(HojaSerializer):
    acciones = AccionSerializer(many=True, read_only=True)
    incidencias = IncidenciaSerializer(many=True, read_only=True)
    resumen = serializers.SerializerMethodField()

    class Meta(HojaSerializer.Meta):
        fields = HojaSerializer.Meta.fields + ["acciones", "incidencias", "resumen"]

    def get_resumen(self, hoja):
        return resumen_hoja(hoja)


class OrdenSerializer(serializers.ModelSerializer):
    tipo_orden_codigo = serializers.CharField(source="tipo_orden.codigo", read_only=True, default=None)
    categoria_texto = serializers.CharField(source="get_categoria_display", read_only=True)
    brigada_pendiente_nombre = serializers.CharField(source="brigada_pendiente.nombre", read_only=True, default=None)
    estado_texto = serializers.CharField(source="get_estado_display", read_only=True)
    ultima_fecha = serializers.SerializerMethodField(help_text="Fecha de la última acción sobre la orden.")
    ultimo_centro = serializers.SerializerMethodField(help_text="Código del centro de la última acción.")

    class Meta:
        model = OrdenServicio
        fields = ["id", "etiqueta", "categoria", "categoria_texto", "numero_orden", "numero_servicio", "tipo_orden", "tipo_orden_codigo",
                  "fecha_reporte", "estado", "estado_texto",
                  "brigada_pendiente", "brigada_pendiente_nombre", "ultima_fecha", "ultimo_centro"]

    def _ultima(self, orden):
        acciones = sorted(orden.acciones.all(), key=lambda a: (a.hoja.fecha, a.pk))
        return acciones[-1] if acciones else None

    def get_ultima_fecha(self, orden):
        ultima = self._ultima(orden)
        return ultima.hoja.fecha.isoformat() if ultima else None

    def get_ultimo_centro(self, orden):
        ultima = self._ultima(orden)
        return ultima.centro.codigo if ultima and ultima.centro_id else None


class HistorialSerializer(serializers.ModelSerializer):
    """Una línea del historial de un servicio: quién lo trabajó, cuándo y con qué resultado (calidad / reincidencias)."""

    fecha = serializers.DateField(source="hoja.fecha")
    brigada = serializers.CharField(source="hoja.brigada.nombre")
    operarios = serializers.SerializerMethodField()
    claves = serializers.SerializerMethodField()
    estado = serializers.SerializerMethodField()

    class Meta:
        model = Accion
        fields = ["id", "fecha", "brigada", "operarios", "claves", "estado", "ok", "tiempo_real_min"]

    def get_operarios(self, accion):
        return [o.nombre for o in accion.hoja.operarios.all()]

    def get_claves(self, accion):
        return [c.codigo for c in accion.claves.all()]

    def get_estado(self, accion):
        return accion.estado
