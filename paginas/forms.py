"""Validación server-side de los formularios de contacto e institucional.

Mismas reglas y mensajes que los esquemas zod de src/app/api/*/route.ts.
"""

from django import forms


def _texto(min_len: int, mensaje: str, max_len: int = 200, **kwargs) -> forms.CharField:
    # strip=False: zod valida la longitud del texto tal cual llega.
    return forms.CharField(
        min_length=min_len,
        max_length=max_len,
        strip=False,
        error_messages={"required": mensaje, "min_length": mensaje, "max_length": "Texto demasiado largo"},
        **kwargs,
    )


class HoneypotMixin(forms.Form):
    """Campo trampa para bots: los humanos no lo ven, así que debe llegar vacío."""

    website = forms.CharField(required=False, strip=False)

    def es_spam(self) -> bool:
        return bool(self.cleaned_data.get("website"))


class ContactForm(HoneypotMixin):
    nombre = _texto(2, "El nombre debe tener al menos 2 caracteres")
    apellido = _texto(2, "El apellido debe tener al menos 2 caracteres")
    email = forms.EmailField(
        max_length=254,
        error_messages={"required": "Correo electrónico inválido", "invalid": "Correo electrónico inválido",
                        "max_length": "Correo electrónico inválido"},
    )
    celular = _texto(7, "El celular debe tener al menos 7 dígitos", max_len=30)
    mensaje = _texto(10, "El mensaje debe tener al menos 10 caracteres", max_len=5000)

    field_order = ["nombre", "apellido", "email", "celular", "mensaje", "website"]


class InstitucionalForm(HoneypotMixin):
    name = _texto(2, "El nombre debe tener al menos 2 caracteres")
    company = _texto(2, "La empresa debe tener al menos 2 caracteres")
    email = forms.EmailField(
        max_length=254,
        error_messages={"required": "Correo electrónico inválido", "invalid": "Correo electrónico inválido",
                        "max_length": "Correo electrónico inválido"},
    )
    message = forms.CharField(required=False, strip=False, max_length=5000,
                              error_messages={"max_length": "Texto demasiado largo"})
    newsletter = forms.BooleanField(required=False)

    field_order = ["name", "company", "email", "message", "newsletter", "website"]

    def clean_newsletter(self):
        # z.boolean().optional(): solo se acepta true/false (o ausente).
        valor = self.data.get("newsletter")
        if valor is not None and not isinstance(valor, bool):
            raise forms.ValidationError("Valor inválido para newsletter")
        return bool(valor)


def primer_error(form: forms.Form) -> str:
    """Primer mensaje de error, en el orden de los campos (como issues[0] de zod)."""
    for campo in form.fields:
        if campo in form.errors:
            return form.errors[campo][0]
    return next(iter(form.non_field_errors()), "Datos inválidos")
