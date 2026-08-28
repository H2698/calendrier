from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile


@receiver(post_save, sender=get_user_model())
def ensure_user_profile(sender, instance, created, **kwargs):
    if not created:
        return

    Profile.objects.create(
        user=instance,
        full_name=instance.get_full_name() or instance.get_username(),
        email=instance.email.strip().lower() or None,
        role=Profile.Role.ADMIN if instance.is_superuser else Profile.Role.MEMBER,
        is_active=instance.is_active,
    )
