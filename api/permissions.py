from rest_framework.permissions import DjangoModelPermissions


class PermisosDeModelo(DjangoModelPermissions):
    """Usa los permisos de Django de cada rol (Probador, Especialista, Jefe), también para consultar.

    - Consultar exige el permiso 'ver' del modelo; crear/ejecutar acciones exige 'añadir'; modificar, 'cambiar'.
    """

    perms_map = {
        **DjangoModelPermissions.perms_map,
        "GET": ["%(app_label)s.view_%(model_name)s"],
        "OPTIONS": ["%(app_label)s.view_%(model_name)s"],
        "HEAD": ["%(app_label)s.view_%(model_name)s"],
    }
