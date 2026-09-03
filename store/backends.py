from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User

from store.phone import normalize_et_phone


class UsernameOrEmailBackend(ModelBackend):
    """Allow authentication using either username (phone) or email.

    Phone numbers are matched in every common Ethiopian spelling
    (0911…, +251911…, 251911…, 911…) because the username column holds the
    local ``09XXXXXXXX`` form.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get("username")
        if username is None or password is None:
            return None

        username = username.strip()
        user = None
        if "@" in username:
            user = User.objects.filter(email__iexact=username).first()
        if user is None:
            user = User.objects.filter(username__iexact=username).first()
        if user is None:
            normalized = normalize_et_phone(username)
            if normalized and normalized != username:
                user = User.objects.filter(username=normalized).first()
        if user is None:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
