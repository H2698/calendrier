from datetime import timedelta
import json

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from pywebpush import WebPushException, webpush

from .models import Notification


@transaction.atomic
def schedule_appointment_notifications(appointment, notification_type=Notification.Type.CREATED):
    members = list(
        appointment.members.filter(
            Q(profile__in_app_notifications_enabled=True)
            | Q(profile__browser_notifications_enabled=True)
        )
    )
    if notification_type == Notification.Type.REMINDER:
        Notification.objects.filter(appointment=appointment, type=notification_type, sent_at__isnull=True).delete()
    for member in members:
        if notification_type == Notification.Type.REMINDER:
            from apps.core.models import AgencySettings

            scheduled = appointment.start_at - timedelta(
                minutes=AgencySettings.load().reminder_minutes
            )
        else:
            scheduled = timezone.now()
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
    with transaction.atomic():
        now = timezone.now()
        due = list(
            Notification.objects.select_for_update()
            .filter(sent_at__isnull=True, scheduled_for__lte=now)
            # Profile is a reverse one-to-one relation, therefore joining it
            # creates a nullable outer join that PostgreSQL cannot lock with
            # FOR UPDATE. Prefetch it separately while locking notifications.
            .select_related('user')
            .prefetch_related('user__profile', 'user__push_subscriptions')
            .order_by('scheduled_for')
        )
        for notification in due:
            send_web_push(notification)
            notification.sent_at = now
            notification.save(update_fields=('sent_at',))
    return len(due)


def send_web_push(notification):
    if not notification.user.profile.browser_notifications_enabled:
        return {'sent': 0, 'failed': 0, 'stale': 0, 'configured': True, 'enabled': False}
    if not settings.VAPID_PRIVATE_KEY or not settings.VAPID_PUBLIC_KEY:
        return {'sent': 0, 'failed': 0, 'stale': 0, 'configured': False}

    data = json.dumps(
        {
            'title': notification.title,
            'body': notification.message,
            'url': '/notifications/',
            'tag': f'notification-{notification.id}',
        }
    )
    result = {'sent': 0, 'failed': 0, 'stale': 0, 'configured': True}
    for subscription in list(notification.user.push_subscriptions.all()):
        try:
            webpush(
                subscription_info={
                    'endpoint': subscription.endpoint,
                    'keys': {'p256dh': subscription.p256dh, 'auth': subscription.auth},
                },
                data=data,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={'sub': settings.VAPID_SUBJECT},
                ttl=3600,
                timeout=10,
            )
        except WebPushException as exc:
            status_code = getattr(exc.response, 'status_code', None)
            if status_code in {404, 410}:
                subscription.delete()
                result['stale'] += 1
            else:
                result['failed'] += 1
        else:
            subscription.last_used_at = timezone.now()
            subscription.save(update_fields=('last_used_at',))
            result['sent'] += 1
    return result
