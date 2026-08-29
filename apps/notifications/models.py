import uuid

from django.conf import settings
from django.db import models

from apps.calendar_app.models import Appointment


class Notification(models.Model):
    class Type(models.TextChoices):
        CREATED = 'appointment_created', 'Rendez-vous créé'
        UPDATED = 'appointment_updated', 'Rendez-vous modifié'
        CANCELLED = 'appointment_cancelled', 'Rendez-vous annulé'
        REMINDER = 'appointment_reminder', 'Rappel rendez-vous'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    type = models.CharField(max_length=40, choices=Type.choices, db_index=True)
    title = models.CharField(max_length=180)
    message = models.TextField()
    is_read = models.BooleanField(default=False, db_index=True)
    scheduled_for = models.DateTimeField(null=True, blank=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [models.UniqueConstraint(fields=('user', 'appointment', 'type'), name='unique_user_appointment_notification_type')]
        indexes = [models.Index(fields=('user', 'is_read', 'created_at'))]
