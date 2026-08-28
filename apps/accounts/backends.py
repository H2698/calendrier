from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailBackend(ModelBackend):
    """Authenticate internal users with an email address and password."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        identifier = (kwargs.get('email') or username or '').strip()
        if not identifier or password is None:
            return None

        user_model = get_user_model()
        try:
            user = user_model._default_manager.filter(
                Q(email__iexact=identifier) | Q(username__iexact=identifier)
            ).distinct().get()
        except (user_model.DoesNotExist, user_model.MultipleObjectsReturned):
            user_model().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            profile = getattr(user, 'profile', None)
            if profile and profile.is_active:
                return user
        return None

    def get_user(self, user_id):
        """Return disabled users so middleware can actively clear their session."""
        user_model = get_user_model()
        try:
            return user_model._default_manager.get(pk=user_id)
        except user_model.DoesNotExist:
            return None
