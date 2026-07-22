from django import forms
from django.forms import inlineformset_factory

from .models import Product, ProductAIDraft, ProductImages


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
    # Sizes are stored as ProductSizeStock rows (single source of truth); the
    # view applies this field via store.services.inventory.set_product_sizes.
    available_sizes = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "Comma-separated, e.g. XS, S, M, L",
            }
        ),
    )

    class Meta:
        model = Product
        fields = [
            "title",
            "slug",
            "sku",
            "short_description",
            "seo_title",
            "seo_description",
            "image_alt_text",
            "detail_description",
            "material",
            "color",
            "fit_notes",
            "care_notes",
            "delivery_note",
            "return_note",
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
            "seo_description": forms.Textarea(attrs={"rows": 3}),
            "detail_description": forms.Textarea(attrs={"rows": 8}),
            "fit_notes": forms.Textarea(attrs={"rows": 3}),
            "care_notes": forms.Textarea(attrs={"rows": 3}),
            "delivery_note": forms.TextInput(attrs={"placeholder": "Delivery promise shown on PDP"}),
            "return_note": forms.TextInput(attrs={"placeholder": "Return/support note shown on PDP"}),
            "price": forms.NumberInput(attrs={"min": 0, "step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = self.fields["category"].queryset.order_by("title")
        self.fields["brand"].queryset = self.fields["brand"].queryset.order_by("title")
        if self.instance.pk and "available_sizes" not in self.initial:
            self.initial["available_sizes"] = self.instance.available_sizes
        _decorate_dashboard_fields(self.fields)

    def clean_available_sizes(self):
        from store.services.inventory import parse_size_list

        return ", ".join(parse_size_list(self.cleaned_data.get("available_sizes") or ""))


class ProductAIDraftForm(forms.ModelForm):
    class Meta:
        model = ProductAIDraft
        fields = [
            "sku",
            "vendor_hint",
            "price",
            "reference_image",
            "secondary_reference_image",
            "cover_image",
        ]
        widgets = {
            "sku": forms.TextInput(attrs={"placeholder": "Vendor SKU / source code"}),
            "vendor_hint": forms.TextInput(attrs={"placeholder": "Manual local vendor name"}),
            "price": forms.NumberInput(attrs={"min": 0, "step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reference_image"].required = True
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

def decorate_dashboard_formset(formset):
    for form in formset.forms:
        _decorate_dashboard_fields(form.fields)
    _decorate_dashboard_fields(formset.empty_form.fields)
    return formset
