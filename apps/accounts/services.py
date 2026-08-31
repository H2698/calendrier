from datetime import timedelta
import hashlib
import hmac

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import log_activity

from .models import LoginThrottle, Profile
from .permissions import can_delete_team_member


LOGIN_FAILURE_LIMIT = 5
LOGIN_WINDOW = timedelta(minutes=15)


def login_throttle_key(request, email):
    forwarded_for = request.headers.get('X-Forwarded-For', '')
    client_ip = forwarded_for.split(',')[0].strip() or request.META.get(
        'REMOTE_ADDR', 'unknown'
    )
    identifier = f'{client_ip}|{email.strip().lower()}'
    return hmac.new(
        settings.SECRET_KEY.encode(), identifier.encode(), hashlib.sha256
    ).hexdigest()


def login_blocked_until(key):
    now = timezone.now()
    throttle = LoginThrottle.objects.filter(key=key).first()
    if not throttle:
        return None
    if throttle.blocked_until and throttle.blocked_until > now:
        return throttle.blocked_until
    if now - throttle.window_started >= LOGIN_WINDOW:
        LoginThrottle.objects.filter(key=key).delete()
    return None


@transaction.atomic
def record_login_failure(key):
    now = timezone.now()
    throttle, _ = LoginThrottle.objects.select_for_update().get_or_create(
        key=key,
        defaults={'window_started': now},
    )
    if now - throttle.window_started >= LOGIN_WINDOW:
        throttle.failures = 0
        throttle.window_started = now
        throttle.blocked_until = None
    throttle.failures += 1
    if throttle.failures >= LOGIN_FAILURE_LIMIT:
        throttle.blocked_until = now + LOGIN_WINDOW
    throttle.save()
    return throttle.blocked_until


def clear_login_failures(key):
    LoginThrottle.objects.filter(key=key).delete()


@transaction.atomic
def create_user_account(
    *,
    email,
    password,
    full_name,
    role=Profile.Role.MEMBER,
    calendar_color='#2563EB',
    is_active=True,
    actor=None,
):
    normalized_email = get_user_model().objects.normalize_email(email).strip().lower()
    if not normalized_email:
        raise ValidationError({'email': 'Une adresse e-mail est obligatoire.'})
    if role not in Profile.Role.values:
        raise ValidationError({'role': 'Rôle utilisateur invalide.'})
    if get_user_model().objects.filter(
        email__iexact=normalized_email
    ).exists():
        raise ValidationError({'email': 'Cette adresse e-mail existe déjà.'})

    name_parts = full_name.strip().split(maxsplit=1)
    user = get_user_model().objects.create_user(
        username=normalized_email,
        email=normalized_email,
        password=password,
        first_name=name_parts[0] if name_parts else '',
        last_name=name_parts[1] if len(name_parts) > 1 else '',
        is_active=is_active,
        is_staff=role == Profile.Role.ADMIN,
    )
    profile = user.profile
    profile.full_name = full_name.strip()
    profile.email = normalized_email
    profile.role = role
    profile.calendar_color = calendar_color
    profile.is_active = is_active
    profile.full_clean()
    profile.save()
    if actor:
        log_activity(
            actor=actor, action='user_created', entity_type='user',
            entity_id=user.id,
            new_values={
                'full_name': profile.full_name,
                'email': profile.email,
                'role': profile.role,
                'calendar_color': profile.calendar_color,
                'is_active': profile.is_active,
            },
        )
    return user


def _lock_profile_for_update(user):
    # Use the same lock order as deletion so a simultaneous edit cannot
    # overwrite the archival marker with a stale profile instance.
    get_user_model().objects.select_for_update().get(pk=user.pk)
    user.refresh_from_db()
    user.profile = Profile.objects.select_for_update().get(user_id=user.pk)
    return user.profile


@transaction.atomic
def set_account_active(*, user, is_active, actor=None):
    _lock_profile_for_update(user)
    if user.profile.deleted_at:
        raise ValidationError({'is_active': 'Un membre supprimé ne peut pas être réactivé ici.'})
    old_is_active = user.is_active and user.profile.is_active
    user.is_active = is_active
    user.save(update_fields=('is_active',))
    user.profile.is_active = is_active
    user.profile.save(update_fields=('is_active', 'updated_at'))
    if actor and old_is_active != is_active:
        log_activity(
            actor=actor,
            action='user_enabled' if is_active else 'user_disabled',
            entity_type='user', entity_id=user.id,
            old_values={'is_active': old_is_active},
            new_values={'is_active': is_active},
        )


@transaction.atomic
def update_user_account(*, actor, user, data):
    if not isinstance(data, dict):
        raise ValidationError('Les données utilisateur doivent être un objet.')
    profile = _lock_profile_for_update(user)
    if profile.deleted_at:
        raise ValidationError({'is_active': 'Un membre supprimé ne peut plus être modifié.'})
    old_values = {
        'full_name': profile.full_name,
        'email': profile.email,
        'role': profile.role,
        'calendar_color': profile.calendar_color,
        'is_active': user.is_active and profile.is_active,
    }
    if user == actor and data.get('is_active') is False:
        raise ValidationError(
            {'is_active': 'Vous ne pouvez pas désactiver votre propre compte.'}
        )

    raw_email = data.get('email', profile.email)
    if not isinstance(raw_email, str) or not raw_email.strip():
        raise ValidationError({'email': 'Une adresse e-mail est obligatoire.'})
    if 'is_active' in data and not isinstance(data['is_active'], bool):
        raise ValidationError({'is_active': 'L’état du compte doit être un booléen.'})
    email = raw_email.strip().lower()
    if get_user_model().objects.exclude(pk=user.pk).filter(
        email__iexact=email
    ).exists():
        raise ValidationError({'email': 'Cette adresse e-mail existe déjà.'})
    for field in ('full_name', 'role', 'calendar_color'):
        if field in data:
            setattr(profile, field, data[field])
    profile.email = email
    desired_active = bool(data.get('is_active', old_values['is_active']))
    profile.is_active = desired_active
    profile.full_clean()
    profile.save()

    name_parts = profile.full_name.strip().split(maxsplit=1)
    user.username = email
    user.email = email
    user.first_name = name_parts[0] if name_parts else ''
    user.last_name = name_parts[1] if len(name_parts) > 1 else ''
    user.is_staff = profile.role == Profile.Role.ADMIN
    user.is_active = desired_active
    user.save(update_fields=(
        'username', 'email', 'first_name', 'last_name', 'is_staff', 'is_active'
    ))

    new_values = {
        'full_name': profile.full_name,
        'email': profile.email,
        'role': profile.role,
        'calendar_color': profile.calendar_color,
        'is_active': desired_active,
    }
    if {**old_values, 'is_active': desired_active} != new_values:
        log_activity(
            actor=actor, action='user_updated', entity_type='user',
            entity_id=user.id, old_values=old_values, new_values=new_values,
        )
    if old_values['role'] != new_values['role']:
        log_activity(
            actor=actor, action='user_role_changed', entity_type='user',
            entity_id=user.id,
            old_values={'role': old_values['role']},
            new_values={'role': new_values['role']},
        )
    if old_values['is_active'] != desired_active:
        log_activity(
            actor=actor,
            action='user_enabled' if desired_active else 'user_disabled',
            entity_type='user', entity_id=user.id,
            old_values={'is_active': old_values['is_active']},
            new_values={'is_active': desired_active},
        )
    return user


@transaction.atomic
def delete_team_member(*, actor, user):
    # Lock the two records separately: PostgreSQL cannot lock a nullable
    # reverse one-to-one join. No appointment or audit row is deleted.
    user = get_user_model().objects.select_for_update().get(pk=user.pk)
    profile = Profile.objects.select_for_update().get(user_id=user.pk)
    user.profile = profile
    if not can_delete_team_member(actor, user):
        raise PermissionDenied
    old_values = {
        'full_name': profile.full_name,
        'email': profile.email,
        'role': profile.role,
        'is_active': user.is_active and profile.is_active,
        'deleted_at': profile.deleted_at,
    }
    profile.deleted_at = timezone.now()
    profile.is_active = False
    profile.in_app_notifications_enabled = False
    profile.browser_notifications_enabled = False
    profile.save(update_fields=(
        'deleted_at', 'is_active', 'in_app_notifications_enabled',
        'browser_notifications_enabled', 'updated_at',
    ))
    user.is_active = False
    user.save(update_fields=('is_active',))
    log_activity(
        actor=actor, action='user_deleted', entity_type='user', entity_id=user.pk,
        old_values=old_values,
        new_values={'is_active': False, 'deleted_at': profile.deleted_at},
    )
    return user
