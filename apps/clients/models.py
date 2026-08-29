import uuid

from django.conf import settings
from django.db import models


class ActiveClientManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(archived_at__isnull=True)


class Client(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=180, db_index=True)
    company_name = models.CharField(max_length=180, blank=True, db_index=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_clients',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = models.Manager()
    active = ActiveClientManager()

    class Meta:
        ordering = ('name', 'company_name')
        indexes = [
            models.Index(fields=('archived_at', 'name')),
            models.Index(fields=('created_at',)),
        ]

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.company_name = self.company_name.strip()
        self.phone = self.phone.strip()
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @property
    def is_archived(self):
        return self.archived_at is not None

    def __str__(self):
        return self.name
