from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Notification


@transaction.atomic
def schedule_appointment_notifications(appointment, notification_type=Notification.Type.CREATED):
    members = list(appointment.members.all())
    if notification_type == Notification.Type.REMINDER:
        Notification.objects.filter(appointment=appointment, type=notification_type, sent_at__isnull=True).delete()
    for member in members:
        scheduled = appointment.start_at - timedelta(minutes=30) if notification_type == Notification.Type.REMINDER else timezone.now()
        Notification.objects.update_or_create(
            user=member, appointment=appointment, type=notification_type,
            defaults={'title': appointment.title, 'message': _message(appointment, notification_type), 'scheduled_for': scheduled, 'sent_at': None, 'is_read': False},
        )


def _message(appointment, notification_type):
    labels = {
        Notification.Type.CREATED: 'Un rendez-vous vous a été assigné.',
        Notification.Type.UPDATED: 'Un rendez-vous assigné a été modifié.',
        Notification.Type.CANCELLED: 'Un rendez-vous assigné a été annulé.',
        Notification.Type.REMINDER: 'Votre rendez-vous commence dans 30 minutes.',
    }
    return labels[notification_type]


def dispatch_due_notifications():
    now = timezone.now()
    due = Notification.objects.select_for_update().filter(sent_at__isnull=True, scheduled_for__lte=now)
    count = due.update(sent_at=now)
    return count
