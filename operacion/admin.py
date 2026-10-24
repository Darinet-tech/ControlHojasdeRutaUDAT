from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import Accion, HojaDeRuta, Incidencia, OrdenServicio
from .services import acciones_abiertas, cerrar_hoja, finalizar_incidencia, iniciar_incidencia, validar_operarios_libres


admin.site.site_header = "UDAT · Unidad de Asistencia Técnica"
admin.site.site_title = "UDAT"
admin.site.index_title = "Administración"


class AuditableAdmin(admin.ModelAdmin):
    def save_model(self, request, obj, form, change):
        if not change:
            obj.creado_por = request.user
        obj.modificado_por = request.user
        super().save_model(request, obj, form, change)


class AccionInline(admin.StackedInline):
    """Aquí solo se registran las acciones. El cierre (OK / pasar a otra brigada) se hace con las reglas de
    operacion/services.py, que generan la hora de fin y el tiempo real; en la fase 2 serán botones de la pantalla."""

    model = Accion
    extra = 0
    autocomplete_fields = ("orden", "claves")
    fields = ("numero", "orden", "centro", "claves", "descripcion_trabajo")


class IncidenciaInline(admin.TabularInline):
    """Al guardar una fila nueva arranca el contador (inicio = ahora). Se detiene con la acción
    'Finalizar la incidencia en curso' o al cerrar la hoja."""

    model = Incidencia
    extra = 0
    fields = ("causa", "observaciones", "inicio", "fin")
    readonly_fields = ("inicio", "fin")

    def has_delete_permission(self, request, obj=None):
        return False


class HojaDeRutaForm(forms.ModelForm):
    class Meta:
        model = HojaDeRuta
        fields = "__all__"

    def clean(self):
        datos = super().clean()
        if datos.get("fecha") and datos.get("operarios"):  # un operario no puede estar en dos hojas el mismo día
            try:
                validar_operarios_libres(datos["fecha"], datos["operarios"], excluir_hoja=self.instance)
            except ValidationError as error:
                self.add_error("operarios", error)
        return datos


@admin.register(HojaDeRuta)
class HojaDeRutaAdmin(AuditableAdmin):
    form = HojaDeRutaForm
    list_display = ("fecha", "brigada", "centros_lista", "vehiculo", "incidencia_activa", "cerrada")
    list_filter = ("fecha", "brigada", "centros", "cerrada")
    search_fields = ("brigada__nombre", "centros__nombre", "centros__codigo", "vehiculo__chapa")
    filter_horizontal = ("operarios", "centros")
    date_hierarchy = "fecha"
    readonly_fields = ("cerrada", "cerrada_en", "cerrada_por")
    inlines = [AccionInline, IncidenciaInline]
    actions = ["finalizar_incidencia_en_curso", "cerrar_hojas"]

    @admin.display(description="Centros")
    def centros_lista(self, hoja):
        return hoja.etiqueta_centros

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("centros")

    @admin.display(description="Incidencia activa")
    def incidencia_activa(self, hoja):
        activa = hoja.incidencias.filter(fin__isnull=True).select_related("causa").first()
        return str(activa.causa) if activa else "-"

    def has_change_permission(self, request, obj=None):
        # Una hoja cerrada ya no se edita (solo el superusuario puede corregirla).
        if obj is not None and obj.cerrada and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def save_formset(self, request, form, formset, change):
        instancias = formset.save(commit=False)
        if formset.model is Incidencia:
            for obj in instancias:
                if obj.pk:  # una incidencia existente solo permite cambiar las observaciones
                    Incidencia.objects.filter(pk=obj.pk).update(observaciones=obj.observaciones)
                    continue
                try:
                    iniciar_incidencia(form.instance, obj.causa, request.user, obj.observaciones)
                except ValidationError as error:
                    self.message_user(request, " ".join(error.messages), messages.ERROR)
            return
        centros_de_la_hoja = {c.pk for c in form.instance.centros.all()}
        for obj in instancias:
            if obj.centro_id is None and len(centros_de_la_hoja) == 1:
                obj.centro_id = next(iter(centros_de_la_hoja))  # una hoja de un solo centro: es el de todos sus servicios
            if obj.centro_id not in centros_de_la_hoja:
                self.message_user(request, f"El servicio {obj.orden}: indique un centro de los de la hoja.", messages.ERROR)
                continue
            if not obj.pk:
                obj.creado_por = request.user
            obj.modificado_por = request.user
            obj.save()
        formset.save_m2m()
        for obj in formset.deleted_objects:
            obj.delete()

    @admin.action(description="Finalizar la incidencia en curso (el operario confirmó el cambio de estado)",
                  permissions=["change"])
    def finalizar_incidencia_en_curso(self, request, queryset):
        for hoja in queryset:
            incidencia = finalizar_incidencia(hoja, request.user)
            if incidencia:
                self.message_user(request, f"{hoja}: incidencia {incidencia.causa} finalizada ({incidencia.minutos()} min).")
            else:
                self.message_user(request, f"{hoja}: no tenía incidencia activa.", messages.WARNING)

    @admin.action(description="Cerrar la hoja de ruta (fin del día)", permissions=["change"])
    def cerrar_hojas(self, request, queryset):
        for hoja in queryset:
            sin_cerrar = acciones_abiertas(hoja).count()
            try:
                cerrar_hoja(hoja, request.user)
            except ValidationError as error:
                self.message_user(request, f"{hoja}: {' '.join(error.messages)}", messages.ERROR)
                continue
            aviso = f" {sin_cerrar} servicio(s) quedaron como no visitados y pasan al siguiente día." if sin_cerrar else ""
            self.message_user(request, f"{hoja}: cerrada.{aviso}", messages.WARNING if sin_cerrar else messages.SUCCESS)


@admin.register(OrdenServicio)
class OrdenServicioAdmin(AuditableAdmin):
    list_display = ("numero_servicio", "tipo_orden", "estado", "brigada_pendiente", "fecha_reporte")
    list_filter = ("estado", "tipo_orden", "brigada_pendiente")
    search_fields = ("numero_servicio",)


@admin.register(Accion)
class AccionAdmin(AuditableAdmin):
    list_display = ("orden", "hoja", "ok", "pasada_a", "tiempo_real_min")
    list_filter = ("ok", "hoja__brigada", "hoja__fecha")
    search_fields = ("orden__numero_servicio",)
    autocomplete_fields = ("orden", "hoja")
    filter_horizontal = ("claves",)
    readonly_fields = ("ok", "pasada_a", "hora_fin", "tiempo_real_min", "cliente_contactado", "certificada_por",
                       "certificada_en")
