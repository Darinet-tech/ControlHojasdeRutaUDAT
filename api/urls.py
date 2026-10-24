from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("brigadas", views.BrigadaViewSet, basename="brigada")
router.register("centros", views.CentroViewSet, basename="centro")
router.register("vehiculos", views.VehiculoViewSet, basename="vehiculo")
router.register("operarios", views.OperarioViewSet, basename="operario")
router.register("claves", views.ClaveViewSet, basename="clave")
router.register("tipos-orden", views.TipoOrdenViewSet, basename="tipoorden")
router.register("tipos-mantenimiento", views.TipoMantenimientoViewSet, basename="tipomantenimiento")
router.register("tipos-trabajo", views.TipoTrabajoViewSet, basename="tipotrabajo")
router.register("causas-incidencia", views.CausaIncidenciaViewSet, basename="causaincidencia")
router.register("hojas", views.HojaViewSet, basename="hoja")
router.register("acciones", views.AccionViewSet, basename="accion")
router.register("ordenes", views.OrdenViewSet, basename="orden")

urlpatterns = [
    path("auth/login/", views.LoginView.as_view()),
    path("auth/logout/", views.LogoutView.as_view()),
    path("auth/me/", views.SesionView.as_view()),
    path("inicio/", views.InicioView.as_view()),
    path("analisis/", views.AnalisisView.as_view()),
    path("resumen/", views.ResumenView.as_view()),
    path("informe-diario/", views.InformeDiarioView.as_view()),
    path("", include(router.urls)),
]
