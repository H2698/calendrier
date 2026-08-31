from functools import wraps

from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied

from .models import Profile


def user_role(user):
    if not user.is_authenticated:
        return None
    profile = getattr(user, 'profile', None)
    return profile.role if user.is_active and profile and profile.is_active and not profile.deleted_at else None


def can_delete_team_member(actor, user):
    return (
        user_role(actor) in {Profile.Role.ADMIN, Profile.Role.MANAGER}
        and actor.pk != user.pk
        and not user.is_superuser
        and user.profile.role != Profile.Role.ADMIN
        and user.profile.deleted_at is None
    )


def role_required(*allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                raise PermissionDenied
            if user_role(request.user) not in allowed_roles:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


calendar_manager_required = role_required(Profile.Role.ADMIN, Profile.Role.MANAGER)
admin_required = role_required(Profile.Role.ADMIN)


class RoleRequiredMixin(AccessMixin):
    allowed_roles = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if user_role(request.user) not in self.allowed_roles:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
