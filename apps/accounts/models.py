import uuid

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models


class Profile(models.Model):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Administrateur'
        MANAGER = 'manager', 'Gérante'
        MEMBER = 'member', 'Membre'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    full_name = models.CharField(max_length=150)
    email = models.EmailField(unique=True, null=True, blank=True)
    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.MEMBER,
        db_index=True,
    )
    calendar_color = models.CharField(
        max_length=7,
        default='#2563EB',
        validators=[
            RegexValidator(
                regex=r'^#[0-9A-Fa-f]{6}$',
                message='La couleur doit utiliser le format #RRGGBB.',
            )
        ],
    )
    avatar_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('full_name',)
        indexes = [models.Index(fields=('role', 'is_active'))]

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        if not self.full_name:
            self.full_name = self.user.get_full_name() or self.user.get_username()
        super().save(*args, **kwargs)

    @property
    def can_manage_calendar(self):
        return self.role in {self.Role.ADMIN, self.Role.MANAGER}

    def __str__(self):
        return self.full_name
