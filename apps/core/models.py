from django.conf import settings
from django.core.cache import cache
from django.db import models


class AgencySettings(models.Model):
    agency_name = models.CharField(max_length=150, default='Agency Calendar')
    logo_url = models.URLField(blank=True)
    timezone = models.CharField(max_length=64, default='Africa/Tunis')
    reminder_minutes = models.PositiveSmallIntegerField(default=30)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='agency_settings_updates',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Agency settings'

    @classmethod
    def load(cls):
        settings_record, _ = cls.objects.get_or_create(pk=1)
        return settings_record

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete('agency_timezone')
