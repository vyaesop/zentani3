from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
    UserCreationForm,
    UsernameField,
)
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _

from store.models import Address, OrderGroup, ProductReview, RestockRequest
from store.phone import normalize_et_phone

PHONE_HELP = _("Ethiopian mobile number, e.g. 0911 234 567 or +251 911 234 567.")
PHONE_ERROR = _("Enter a valid Ethiopian mobile number (09… or 07…, 10 digits).")


def clean_phone_value(value, *, required=True):
    """Validate + normalise an Ethiopian mobile number to ``09XXXXXXXX``."""
    raw = (value or "").strip()
    if not raw:
        if required:
            raise forms.ValidationError(PHONE_ERROR)
        return ""
    normalized = normalize_et_phone(raw)
    if not normalized:
        raise forms.ValidationError(PHONE_ERROR)
    return normalized


class RegistrationForm(UserCreationForm):
    full_name = forms.CharField(
        required=True,
        label=_('Full Name'),
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Full Name'), 'autocomplete': 'name'})
    )
    address = forms.CharField(
        required=True,
        label=_('Address'),
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Nearest Location')})
    )
    city = forms.CharField(
        required=True,
        label=_('City'),
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('City')})
    )
    password1 = forms.CharField(label=_('Password'), widget=forms.PasswordInput(attrs={'class':'form-control', 'placeholder':_('Password'), 'autocomplete': 'new-password'}))
    password2 = forms.CharField(label=_("Confirm Password"), widget=forms.PasswordInput(attrs={'class':'form-control', 'placeholder':_('Confirm Password'), 'autocomplete': 'new-password'}))
    email = forms.CharField(required=True, widget=forms.EmailInput(attrs={'class':'form-control', 'placeholder':_('Email Address'), 'autocomplete': 'email'}))

    class Meta:
        model = User
        fields = ['full_name', 'username', 'email', 'address', 'city', 'password1', 'password2']
        labels = {'email': _('Email'), 'username': _('Phone Number')}
        widgets = {'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Phone Number'), 'autocomplete': 'tel', 'inputmode': 'tel'})}
        help_texts = {'username': PHONE_HELP}

    def clean_full_name(self):
        return self.cleaned_data['full_name'].strip()

    def clean_username(self):
        # The username *is* the phone number: normalise so "+251 911…" and
        # "0911…" cannot register twice, and validate it is dial-able.
        normalized = clean_phone_value(self.cleaned_data['username'])
        if User.objects.filter(username=normalized).exists():
            raise forms.ValidationError(_("An account with this phone number already exists. Log in instead."))
        return normalized

    def clean_address(self):
        return self.cleaned_data['address'].strip()

    def clean_city(self):
        return self.cleaned_data['city'].strip()

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()

    def save(self, commit=True):
        user = super().save(commit=False)
        full_name = self.cleaned_data.get('full_name', '').strip()
        if full_name:
            name_parts = full_name.split(None, 1)
            user.first_name = name_parts[0]
            user.last_name = name_parts[1] if len(name_parts) > 1 else ''
        user.email = self.cleaned_data.get('email', '').strip().lower()
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    username = UsernameField(label=_("Phone Number"), widget=forms.TextInput(attrs={'autofocus': True, 'class': 'form-control', 'placeholder':_('Phone Number'), 'autocomplete': 'username', 'inputmode': 'tel'}))
    password = forms.CharField(label=_("Password"), strip=False, widget=forms.PasswordInput(attrs={'autocomplete':'current-password', 'class':'form-control'}))

    def clean_username(self):
        return self.cleaned_data["username"].strip()


class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ['address', 'city', 'phone']
        widgets = {
            'address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Popular place like a restaurant, church, mosque, or landmark')}),
            'city': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('City')}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Phone Number'), 'autocomplete': 'tel', 'inputmode': 'tel'}),
        }
        help_texts = {'phone': PHONE_HELP}

    def clean_phone(self):
        return clean_phone_value(self.cleaned_data.get("phone"))


class ProductReviewForm(forms.ModelForm):
    class Meta:
        model = ProductReview
        fields = ["rating", "title", "comment", "fit_feedback", "image"]
        widgets = {
            "rating": forms.Select(
                choices=[(value, f"{value} star{'s' if value != 1 else ''}") for value in range(5, 0, -1)],
                attrs={"class": "form-control"},
            ),
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": _("Review title")}),
            "comment": forms.Textarea(
                attrs={"class": "form-control", "placeholder": _("Share fit, quality, and overall impression"), "rows": 5}
            ),
            "fit_feedback": forms.RadioSelect,
            "image": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
        }

    def clean_title(self):
        return self.cleaned_data["title"].strip()

    def clean_comment(self):
        return self.cleaned_data["comment"].strip()


class InviteReviewForm(ProductReviewForm):
    """Review left through a tokenised invite link (no account required)."""

    reviewer_name = forms.CharField(
        required=False,
        max_length=150,
        label=_("Your name (shown with the review)"),
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": _("First name is enough")}),
    )

    class Meta(ProductReviewForm.Meta):
        fields = ["reviewer_name", "rating", "title", "comment", "fit_feedback", "image"]

    def clean_reviewer_name(self):
        return (self.cleaned_data.get("reviewer_name") or "").strip()


class RestockRequestForm(forms.ModelForm):
    class Meta:
        model = RestockRequest
        fields = ["email", "size"]
        widgets = {
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": _("Email address")}),
            "size": forms.TextInput(attrs={"class": "form-control", "placeholder": _("Preferred size (optional)")}),
        }

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean_size(self):
        return self.cleaned_data["size"].strip()


class GuestCheckoutForm(forms.Form):
    full_name = forms.CharField(
        max_length=150,
        label=_("Full name"),
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": _("Full name"), "autocomplete": "name"}),
    )
    phone = forms.CharField(
        max_length=20,
        label=_("Phone number"),
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": _("Phone number"), "autocomplete": "tel", "inputmode": "tel"}),
        help_text=PHONE_HELP,
    )
    email = forms.EmailField(
        required=False,
        label=_("Email (optional, for your receipt)"),
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": _("Email address"), "autocomplete": "email"}),
    )
    city = forms.CharField(
        max_length=150,
        label=_("City"),
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": _("City"), "autocomplete": "address-level2"}),
    )
    address = forms.CharField(
        max_length=255,
        label=_("Delivery address"),
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": _("Delivery address"), "autocomplete": "street-address"}),
    )

    def clean_full_name(self):
        value = self.cleaned_data["full_name"].strip()
        if len(value) < 2:
            raise forms.ValidationError(_("Please enter your full name."))
        return value

    def clean_phone(self):
        return clean_phone_value(self.cleaned_data["phone"])

    def clean_email(self):
        return (self.cleaned_data.get("email") or "").strip().lower()

    def clean_city(self):
        return self.cleaned_data["city"].strip()

    def clean_address(self):
        value = self.cleaned_data["address"].strip()
        if len(value) < 5:
            raise forms.ValidationError(_("Please enter a more complete delivery address."))
        return value


class PaymentMethodForm(forms.Form):
    """Payment choice at checkout; only offered when online payments are on."""

    payment_method = forms.ChoiceField(
        required=False,
        choices=OrderGroup.PAYMENT_METHOD_CHOICES,
        widget=forms.RadioSelect,
    )

    def clean_payment_method(self):
        value = (self.cleaned_data.get("payment_method") or OrderGroup.PAYMENT_COD).strip()
        if value == OrderGroup.PAYMENT_CHAPA and not getattr(settings, "ONLINE_PAYMENTS_ENABLED", False):
            raise forms.ValidationError(_("Online payment is not available right now. Please choose cash on delivery."))
        return value or OrderGroup.PAYMENT_COD


class PasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(label=_("Old Password"), strip=False, widget=forms.PasswordInput(attrs={'autocomplete':'current-password', 'auto-focus':True, 'class':'form-control', 'placeholder':_('Current Password')}))
    new_password1 = forms.CharField(label=_("New Password"), strip=False, widget=forms.PasswordInput(attrs={'autocomplete':'new-password', 'class':'form-control', 'placeholder':_('New Password')}), help_text=password_validation.password_validators_help_text_html())
    new_password2 = forms.CharField(label=_("Confirm Password"), strip=False, widget=forms.PasswordInput(attrs={'autocomplete':'new-password', 'class':'form-control', 'placeholder':_('Confirm Password')}))


class PasswordResetForm(PasswordResetForm):
    email = forms.EmailField(label=_("Email"), max_length=254, widget=forms.EmailInput(attrs={'autocomplete':'email', 'class':'form-control'}))


class SetPasswordForm(SetPasswordForm):
    new_password1 = forms.CharField(label=_("New Password"), strip=False, widget=forms.PasswordInput(attrs={'autocomplete':'new-password', 'class':'form-control'}), help_text=password_validation.password_validators_help_text_html())
    new_password2 = forms.CharField(label=_("Confirm Password"), strip=False, widget=forms.PasswordInput(attrs={'autocomplete':'new-password','class':'form-control'}))
