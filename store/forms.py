from django.contrib.auth import password_validation
from store.models import Address
from django import forms
import django
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, UsernameField, PasswordChangeForm, PasswordResetForm, SetPasswordForm
from django.db import models
from django.db.models import fields
from django.forms import widgets
from django.forms.fields import CharField
from django.utils.translation import gettext, gettext_lazy as _



class RegistrationForm(UserCreationForm):
    full_name = forms.CharField(
        required=True,
        label='Full Name',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Full Name'})
    )
    address = forms.CharField(
        required=True,
        label='Address',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nearest Location'})
    )
    city = forms.CharField(
        required=True,
        label='City',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'City'})
    )
    password1 = forms.CharField(label='Password', widget=forms.PasswordInput(attrs={'class':'form-control', 'placeholder':'Password'}))
    password2 = forms.CharField(label="Confirm Password", widget=forms.PasswordInput(attrs={'class':'form-control', 'placeholder':'Confirm Password'}))
    email = forms.CharField(required=True, widget=forms.EmailInput(attrs={'class':'form-control', 'placeholder':'Email Address'}))

    class Meta:
        model = User
        fields = ['full_name', 'username', 'email', 'address', 'city', 'password1', 'password2']
        labels = {'email': 'Email', 'username': _('Phone Number')}
        widgets = {'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder':'Phone Number'})}

    def clean_full_name(self):
        return self.cleaned_data['full_name'].strip()

    def clean_username(self):
        return self.cleaned_data['username'].strip()

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
    username = UsernameField(label=_("Phone Number"), widget=forms.TextInput(attrs={'autofocus': True, 'class': 'form-control', 'placeholder':'Phone Number'}))
    password = forms.CharField(label=_("Password"), strip=False, widget=forms.PasswordInput(attrs={'autocomplete':'current-password', 'class':'form-control'}))

    def clean_username(self):
        return self.cleaned_data["username"].strip()


class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ['address', 'city', 'phone']
        widgets = {'address':forms.TextInput(attrs={'class':'form-control', 'placeholder':'Popular Place like Restaurant, Religious Site, etc.'}), 'city':forms.TextInput(attrs={'class':'form-control', 'placeholder':'City'})}


class PasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(label=_("Old Password"), strip=False, widget=forms.PasswordInput(attrs={'autocomplete':'current-password', 'auto-focus':True, 'class':'form-control', 'placeholder':'Current Password'}))
    new_password1 = forms.CharField(label=_("New Password"), strip=False, widget=forms.PasswordInput(attrs={'autocomplete':'new-password', 'class':'form-control', 'placeholder':'New Password'}), help_text=password_validation.password_validators_help_text_html())
    new_password2 = forms.CharField(label=_("Confirm Password"), strip=False, widget=forms.PasswordInput(attrs={'autocomplete':'new-password', 'class':'form-control', 'placeholder':'Confirm Password'}))


class PasswordResetForm(PasswordResetForm):
    email = forms.EmailField(label=_("Email"), max_length=254, widget=forms.EmailInput(attrs={'autocomplete':'email', 'class':'form-control'}))


class SetPasswordForm(SetPasswordForm):
    new_password1 = forms.CharField(label=_("New Password"), strip=False, widget=forms.PasswordInput(attrs={'autocomplete':'new-password', 'class':'form-control'}), help_text=password_validation.password_validators_help_text_html())
    new_password2 = forms.CharField(label=_("Confirm Password"), strip=False, widget=forms.PasswordInput(attrs={'autocomplete':'new-password','class':'form-control'}))
