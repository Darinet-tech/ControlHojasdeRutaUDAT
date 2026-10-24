from django.core.exceptions import ValidationError as ErrorDjango
from rest_framework.exceptions import ValidationError
from rest_framework.views import exception_handler


def manejador_de_errores(exc, context):
    """Las reglas de negocio (operacion/services.py) lanzan ValidationError de Django: se devuelven como 400."""
    if isinstance(exc, ErrorDjango):
        exc = ValidationError({"detail": exc.messages})
    return exception_handler(exc, context)
