"""Formularios del panel (con el estilo de la tienda)."""

from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.forms import BaseInlineFormSet, inlineformset_factory, modelformset_factory

from carrito.models import Order, ShippingRate, StoreSettings
from core.constants import CATEGORIAS_PRODUCTO
from tienda.models import Product, ProductSize

INPUT = (
    "w-full rounded-xl border border-beige bg-blanco px-3.5 py-2.5 font-cuerpo text-sm text-texto "
    "placeholder:text-texto-claro outline-none transition-colors focus:border-naranja focus:ring-2 focus:ring-naranja/20"
)
INPUT_CHICO = (
    "w-full rounded-lg border border-beige bg-blanco px-2.5 py-1.5 font-cuerpo text-sm text-texto "
    "outline-none focus:border-naranja focus:ring-2 focus:ring-naranja/20"
)
CHECK = "h-4 w-4 rounded border-beige accent-naranja-oscuro"
MOLIENDAS = ["Grano", "Molido"]


def _estilizar(form, chico: bool = False) -> None:
    for name, field in form.fields.items():
        widget = field.widget
        if isinstance(widget, (forms.CheckboxInput,)):
            widget.attrs.setdefault("class", CHECK)
        elif isinstance(widget, forms.CheckboxSelectMultiple):
            widget.attrs.setdefault("class", CHECK)
        elif isinstance(widget, forms.ClearableFileInput):
            widget.attrs.setdefault("class", "block w-full text-sm text-texto file:mr-3 file:rounded-full file:border-0 "
                                    "file:bg-crema file:px-4 file:py-2 file:font-nav file:text-xs file:font-bold "
                                    "file:text-verde-oscuro hover:file:bg-naranja hover:file:text-blanco")
        else:
            widget.attrs.setdefault("class", INPUT_CHICO if chico else INPUT)
    # Ojo: no leer form.errors aquí; dispararía la validación antes de que el
    # formset agregue sus campos (id, DELETE) y se ignoraría «Quitar».


# ── Acceso ──

class LoginForm(AuthenticationForm):
    recordarme = forms.BooleanField(label="Mantener la sesión iniciada en este equipo (7 días)", required=False)

    error_messages = {
        "invalid_login": "Usuario o contraseña incorrectos.",
        "inactive": "Esta cuenta está desactivada.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Usuario"
        self.fields["password"].label = "Contraseña"
        self.fields["username"].widget.attrs.update({"autocomplete": "username", "autofocus": True})
        self.fields["password"].widget.attrs.update({"autocomplete": "current-password"})
        _estilizar(self)

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise forms.ValidationError("Esta cuenta no tiene acceso al panel.", code="no_staff")


class CambiarClaveForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].label = "Contraseña actual"
        self.fields["new_password1"].label = "Contraseña nueva"
        self.fields["new_password2"].label = "Repite la contraseña nueva"
        _estilizar(self)


# ── Pedidos ──

class FiltroPedidos(forms.Form):
    q = forms.CharField(label="Buscar", required=False,
                        widget=forms.TextInput(attrs={"placeholder": "Número, nombre, correo, celular o documento"}))
    estado = forms.ChoiceField(label="Estado", required=False, choices=[("", "Todos los estados")] + Order.STATUS_CHOICES)
    departamento = forms.ChoiceField(label="Departamento", required=False)
    desde = forms.DateField(label="Desde", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    hasta = forms.DateField(label="Hasta", required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from carrito.shipping import DEPARTAMENTOS

        self.fields["departamento"].choices = [("", "Todos")] + [(d, d) for d in DEPARTAMENTOS]
        _estilizar(self)


# ── Productos ──

class ProductoForm(forms.ModelForm):
    grind_options = forms.MultipleChoiceField(
        label="Moliendas disponibles", required=False, choices=[(m, m) for m in MOLIENDAS],
        widget=forms.CheckboxSelectMultiple,
        help_text="Si no marcas ninguna, el producto se vende sin elegir molienda.",
    )
    category = forms.ChoiceField(label="Categoría")

    class Meta:
        model = Product
        fields = [
            "name", "slug", "category", "origin", "description", "price", "weight",
            "grind_options", "image_upload", "featured", "active", "order",
            "optional_products", "accessory_products",
        ]
        labels = {
            "name": "Nombre", "slug": "Dirección web (slug)", "origin": "Origen", "description": "Descripción",
            "price": "Precio (COP)", "weight": "Peso (g)", "image_upload": "Foto del producto",
            "featured": "Destacado (sale en el inicio)", "active": "Visible en la tienda", "order": "Orden",
            "optional_products": "Productos sugeridos", "accessory_products": "Accesorios",
        }
        help_texts = {
            "slug": "Aparece en la dirección: /tienda/<slug>. Solo minúsculas, números y guiones.",
            "price": "Se usa solo si el producto NO tiene tamaños.",
            "weight": "Se usa solo si el producto NO tiene tamaños. Sirve para calcular el envío.",
            "order": "Los números menores salen primero.",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 8}),
            "optional_products": forms.CheckboxSelectMultiple,
            "accessory_products": forms.CheckboxSelectMultiple,
            "image_upload": forms.ClearableFileInput(attrs={"accept": "image/*"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        categorias = list(CATEGORIAS_PRODUCTO)
        for actual in Product.objects.values_list("category", flat=True).distinct():
            if actual and actual not in categorias:
                categorias.append(actual)
        self.fields["category"].choices = [(c, c) for c in categorias]
        otros = Product.objects.order_by("name")
        if self.instance.pk:
            otros = otros.exclude(pk=self.instance.pk)
        self.fields["optional_products"].queryset = otros
        self.fields["accessory_products"].queryset = otros
        # Conserva moliendas que no estén en la lista estándar.
        extra = [g for g in (self.instance.grind_options or []) if g not in MOLIENDAS]
        self.fields["grind_options"].choices = [(m, m) for m in MOLIENDAS + extra]
        # Con tamaños, precio/peso del producto no se usan: no son obligatorios.
        for nombre in ("price", "weight", "order"):
            self.fields[nombre].required = False
        self.fields["image_upload"].help_text = "Reemplaza la foto actual. Mejor cuadrada y de fondo limpio."
        _estilizar(self)

    def clean_slug(self):
        return self.cleaned_data["slug"].strip().lower()

    def clean_price(self):
        return self.cleaned_data.get("price") or 0

    def clean_weight(self):
        return self.cleaned_data.get("weight") or 0

    def clean_order(self):
        return self.cleaned_data.get("order") or 0


class TamanoForm(forms.ModelForm):
    class Meta:
        model = ProductSize
        fields = ["name", "price", "weight", "order"]
        labels = {"name": "Tamaño", "price": "Precio (COP)", "weight": "Peso (g)", "order": "Orden"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["order"].required = False
        _estilizar(self, chico=True)

    def clean_order(self):
        return self.cleaned_data.get("order") or 0

    def clean_price(self):
        precio = self.cleaned_data["price"]
        if precio is not None and precio <= 0:
            raise forms.ValidationError("El precio debe ser mayor a 0.")
        return precio


class TamanosBase(BaseInlineFormSet):
    def clean(self):
        super().clean()
        nombres = set()
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            nombre = (form.cleaned_data.get("name") or "").strip().lower()
            if nombre in nombres:
                raise forms.ValidationError("Hay dos tamaños con el mismo nombre.")
            nombres.add(nombre)

    def tamanos_validos(self) -> int:
        return sum(
            1 for f in self.forms
            if getattr(f, "cleaned_data", None) and not f.cleaned_data.get("DELETE") and f.cleaned_data.get("name")
        )


TamanosFormSet = inlineformset_factory(
    Product, ProductSize, form=TamanoForm, formset=TamanosBase, extra=1, can_delete=True,
)


# ── Envíos ──

class TarifaForm(forms.ModelForm):
    class Meta:
        model = ShippingRate
        fields = ["zona", "departamento", "min_g", "max_g", "price", "active"]
        labels = {"zona": "Zona", "departamento": "Departamento (opcional)", "min_g": "Desde (g)",
                  "max_g": "Hasta (g)", "price": "Precio (COP)", "active": "Activa"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["departamento"].choices = [("", "— Toda la zona —")] + list(self.fields["departamento"].choices)[1:]
        _estilizar(self, chico=True)

    def clean(self):
        data = super().clean()
        if data.get("min_g") is not None and data.get("max_g") is not None and data["min_g"] > data["max_g"]:
            raise forms.ValidationError("El peso «desde» no puede ser mayor que «hasta».")
        return data


TarifasFormSet = modelformset_factory(ShippingRate, form=TarifaForm, extra=1, can_delete=True)


class ConfigTiendaForm(forms.ModelForm):
    class Meta:
        model = StoreSettings
        fields = ["free_shipping_from"]
        labels = {"free_shipping_from": "Envío gratis desde (COP)"}
        help_texts = {"free_shipping_from": "Subtotal desde el cual el envío es gratis. 0 = sin envío gratis."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _estilizar(self)
