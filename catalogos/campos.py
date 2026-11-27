"""Campo de las normas de tiempo: minutos sin redondear (48:34 se guarda como 48,5667 y se vuelve a mostrar como 48:34)."""
from decimal import Decimal, InvalidOperation

from django import forms
from django.db import models


def texto_norma(minutos):
    """49 → «49»; 48,5667 → «48:34» (minutos:segundos); 0,42 (por metro o par) → «0,42»."""
    if minutos is None:
        return ""
    segundos = float(minutos) * 60
    if abs(segundos - round(segundos)) < 0.01:
        m, s = divmod(round(segundos), 60)
        return f"{m}:{s:02d}" if s else str(m)
    return f"{float(minutos):.4f}".rstrip("0").rstrip(".").replace(".", ",")


def leer_norma(texto):
    """Acepta «48:34» (minutos:segundos), «24», «0,42» o «0.42»."""
    texto = str(texto).strip()
    try:
        if ":" in texto:
            m, s = texto.split(":")
            if not (m.isdigit() and s.isdigit() and int(s) < 60):
                raise ValueError
            valor = Decimal(int(m) * 60 + int(s)) / 60
        else:
            valor = Decimal(texto.replace(",", "."))
        valor = valor.quantize(Decimal("0.0001"))
    except (ValueError, InvalidOperation):
        raise forms.ValidationError("Escriba los minutos como 24, como 48:34 (minutos:segundos) o como 0,42.")
    if not 0 <= valor < 10000:
        raise forms.ValidationError("El tiempo debe estar entre 0 y 9999 minutos.")
    return valor


class CampoDeNorma(forms.CharField):
    def prepare_value(self, value):
        return value if value is None or isinstance(value, str) else texto_norma(value)

    def to_python(self, value):
        value = super().to_python(value)
        return leer_norma(value) if value else None

    def has_changed(self, initial, data):
        return texto_norma(initial) != (data or "").strip()

    def run_validators(self, value):
        pass  # el rango ya lo comprueba leer_norma


class MinutosNorma(models.DecimalField):
    """Decimal en la base de datos y número normal (float) en el código, para sumar y comparar sin conversiones."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_digits", 8)
        kwargs.setdefault("decimal_places", 4)
        super().__init__(*args, **kwargs)

    def from_db_value(self, value, expression, connection):
        return None if value is None else float(value)

    def formfield(self, **kwargs):
        return CampoDeNorma(required=not self.blank, label="Minutos", help_text="Ej.: 24, 48:34 (minutos:segundos) o 0,42.")

    def validate(self, value, model_instance):
        super().validate(None if value is None else Decimal(str(value)).quantize(Decimal("0.0001")), model_instance)

    def run_validators(self, value):
        pass
