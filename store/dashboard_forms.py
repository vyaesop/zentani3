from django import forms
from django.forms import inlineformset_factory

from .models import Product, ProductImages, ProductSizeStock


def _decorate_dashboard_fields(fields):
    for field in fields.values():
        widget = field.widget
        existing_class = widget.attrs.get("class", "")

        if isinstance(widget, forms.CheckboxInput):
            widget.attrs["class"] = f"{existing_class} spring-dashboard-check".strip()
            continue

        if isinstance(widget, forms.ClearableFileInput):
            widget.attrs["class"] = f"{existing_class} spring-dashboard-file".strip()
            continue

        if isinstance(widget, forms.HiddenInput):
            continue

        widget.attrs["class"] = f"{existing_class} spring-dashboard-control".strip()


class DashboardProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "title",
            "slug",
            "sku",
            "short_description",
            "detail_description",
            "material",
            "color",
            "fit_notes",
            "care_notes",
            "delivery_note",
            "return_note",
            "available_sizes",
            "stock_quantity",
            "price",
            "product_image",
            "category",
            "brand",
            "is_active",
            "is_featured",
            "is_sold_out",
        ]
        widgets = {
            "short_description": forms.Textarea(attrs={"rows": 4}),
            "detail_description": forms.Textarea(attrs={"rows": 8}),
            "fit_notes": forms.Textarea(attrs={"rows": 3}),
            "care_notes": forms.Textarea(attrs={"rows": 3}),
            "delivery_note": forms.TextInput(attrs={"placeholder": "Delivery promise shown on PDP"}),
            "return_note": forms.TextInput(attrs={"placeholder": "Return/support note shown on PDP"}),
            "available_sizes": forms.TextInput(attrs={"placeholder": "Comma-separated, e.g. XS,S,M,L"}),
            "stock_quantity": forms.NumberInput(attrs={"min": 0}),
            "price": forms.NumberInput(attrs={"min": 0, "step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = self.fields["category"].queryset.order_by("title")
        self.fields["brand"].queryset = self.fields["brand"].queryset.order_by("title")
        _decorate_dashboard_fields(self.fields)


ProductImageFormSet = inlineformset_factory(
    Product,
    ProductImages,
    fields=("image",),
    extra=0,
    can_delete=True,
    widgets={
        "image": forms.ClearableFileInput(),
    },
)


ProductSizeStockFormSet = inlineformset_factory(
    Product,
    ProductSizeStock,
    fields=("size", "quantity"),
    extra=0,
    can_delete=True,
    widgets={
        "size": forms.TextInput(attrs={"placeholder": "Size"}),
        "quantity": forms.NumberInput(attrs={"min": 0}),
    },
)


def decorate_dashboard_formset(formset):
    for form in formset.forms:
        _decorate_dashboard_fields(form.fields)
    _decorate_dashboard_fields(formset.empty_form.fields)
    return formset
