from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Profile


@transaction.atomic
def create_user_account(
    *,
    email,
    password,
    full_name,
    role=Profile.Role.MEMBER,
    calendar_color='#2563EB',
    is_active=True,
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
    return user


@transaction.atomic
def set_account_active(*, user, is_active):
    user.is_active = is_active
    user.save(update_fields=('is_active',))
    user.profile.is_active = is_active
    user.profile.save(update_fields=('is_active', 'updated_at'))
