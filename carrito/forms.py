"""Formulario del checkout (validación del lado del servidor)."""

import re

from django import forms

from .models import Order
from .shipping import DEPARTAMENTOS

# Mismas clases de input que ContactForm.tsx del sitio original.
INPUT_CLASS = (
    "w-full bg-transparent border-0 border-b px-0 py-3 font-cuerpo text-texto outline-none "
    "transition-colors placeholder:text-texto-claro border-beige/40 focus:border-naranja"
)


class CheckoutForm(forms.Form):
    full_name = forms.CharField(
        label="Nombre completo", min_length=3, max_length=150,
        error_messages={"required": "El nombre es obligatorio", "min_length": "Mínimo 3 caracteres"},
        widget=forms.TextInput(attrs={"placeholder": "Tu nombre y apellido", "autocomplete": "name"}),
    )
    email = forms.EmailField(
        label="Email",
        error_messages={"required": "El email es obligatorio", "invalid": "Email inválido"},
        widget=forms.EmailInput(attrs={"placeholder": "tucorreo@ejemplo.com", "autocomplete": "email"}),
    )
    phone = forms.CharField(
        label="Celular", max_length=30,
        error_messages={"required": "El celular es obligatorio"},
        widget=forms.TextInput(attrs={"placeholder": "Ej: 300 123 45 67", "autocomplete": "tel", "type": "tel", "inputmode": "tel"}),
    )
    document_type = forms.ChoiceField(label="Tipo de documento", choices=Order.DOC_CHOICES, initial="CC")
    document = forms.CharField(
        label="Número de documento", max_length=30,
        error_messages={"required": "El documento es obligatorio"},
        widget=forms.TextInput(attrs={"placeholder": "Cédula o NIT", "inputmode": "numeric", "autocomplete": "off"}),
    )
    address = forms.CharField(
        label="Dirección", min_length=5, max_length=200,
        error_messages={"required": "La dirección es obligatoria", "min_length": "Escribe la dirección completa"},
        widget=forms.TextInput(attrs={"placeholder": "Ej: Calle 30 # 14-48", "autocomplete": "address-line1"}),
    )
    address2 = forms.CharField(
        label="Complemento (opcional)", required=False, max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "Apto, torre, barrio…", "autocomplete": "address-line2"}),
    )
    city = forms.CharField(
        label="Ciudad / municipio", min_length=2, max_length=100,
        error_messages={"required": "La ciudad es obligatoria"},
        widget=forms.TextInput(attrs={"placeholder": "Ej: Bucaramanga", "autocomplete": "address-level2"}),
    )
    department = forms.ChoiceField(
        label="Departamento",
        choices=[("", "Selecciona tu departamento")] + [(d, d) for d in DEPARTAMENTOS],
        error_messages={"required": "Selecciona el departamento", "invalid_choice": "Departamento inválido"},
        widget=forms.Select(attrs={"autocomplete": "address-level1"}),
    )
    notes = forms.CharField(
        label="Notas del pedido (opcional)", required=False, max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Indicaciones para la entrega, horario, etc."}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = INPUT_CLASS
            if isinstance(field.widget, forms.Select):
                css += " cursor-pointer"
            field.widget.attrs["class"] = css

    def full_clean(self):
        super().full_clean()
        # Reaplica las clases de error tras validar.
        for name, field in self.fields.items():
            if name in self.errors:
                field.widget.attrs["class"] = field.widget.attrs["class"].replace(
                    "border-beige/40 focus:border-naranja", "border-naranja-oscuro"
                )
                field.widget.attrs["aria-invalid"] = "true"

    def clean_full_name(self):
        return " ".join(self.cleaned_data["full_name"].split())

    def clean_phone(self):
        digits = re.sub(r"\D", "", self.cleaned_data["phone"])
        if not 7 <= len(digits) <= 15:
            raise forms.ValidationError("Escribe un celular válido (mínimo 7 dígitos)")
        return self.cleaned_data["phone"].strip()

    def clean_document(self):
        value = re.sub(r"[\s.]", "", self.cleaned_data["document"])
        if not re.fullmatch(r"[0-9A-Za-z-]{5,20}", value):
            raise forms.ValidationError("Escribe un documento válido (solo números, sin puntos)")
        return value
