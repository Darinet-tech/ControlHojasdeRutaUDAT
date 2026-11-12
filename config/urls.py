"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.http import FileResponse, HttpResponse
from django.urls import include, path, re_path
from django.views.static import serve


def pantalla(request):
    """Página principal de la aplicación web (la pantalla compilada con `npm run build`)."""
    indice = settings.PANTALLA_DIR / 'index.html'
    if not indice.exists():
        return HttpResponse('La pantalla web no está compilada: ejecute "npm ci && npm run build" en la carpeta frontend.',
                            status=503, content_type='text/plain; charset=utf-8')
    return FileResponse(open(indice, 'rb'), content_type='text/html; charset=utf-8')


def archivo_de_la_pantalla(request, path):
    return serve(request, path, document_root=settings.PANTALLA_DIR)


def archivo_estatico(request, path):
    return serve(request, path, document_root=settings.STATIC_ROOT)


urlpatterns = [
    path('', pantalla),
    # archivos de la pantalla compilada (scripts, estilos, logos) y estáticos de /admin (tras `collectstatic`)
    re_path(r'^(?P<path>assets/.+|[\w.-]+\.(?:png|svg|ico|webp|json|txt))$', archivo_de_la_pantalla),
    re_path(r'^static/(?P<path>.+)$', archivo_estatico),
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
    path('api-auth/', include('rest_framework.urls')),  # inicio de sesión para la API navegable
]
