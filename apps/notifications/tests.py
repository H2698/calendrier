from datetime import timedelta
import json
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Profile
from apps.accounts.services import create_user_account
from apps.calendar_app.models import Appointment, AppointmentType
from apps.calendar_app.services import (
    cancel_appointment,
    create_appointment,
    update_appointment,
)

from .models import Notification, PushSubscription
from .services import dispatch_due_notifications


class NotificationTests(TestCase):
    password = 'A-strong-test-password-482!'

    @classmethod
    def setUpTestData(cls):
        cls.admin = create_user_account(
            email='notification-admin@agency.test',
            password=cls.password,
            full_name='Notification Admin',
            role=Profile.Role.ADMIN,
        )
        cls.member = create_user_account(
            email='notification-member@agency.test',
            password=cls.password,
            full_name='Notification Member',
            role=Profile.Role.MEMBER,
        )
        cls.other_member = create_user_account(
            email='notification-other@agency.test',
            password=cls.password,
            full_name='Other Member',
            role=Profile.Role.MEMBER,
        )
        cls.appointment_type = AppointmentType.objects.create(
            name='Notification Meeting', created_by=cls.admin
        )

    def setUp(self):
        self.start_at = timezone.now() + timedelta(hours=3)

    def _create_appointment(self):
        return create_appointment(
            actor=self.admin,
            data={
                'appointment_type': self.appointment_type,
                'title': 'Client meeting',
                'description': '',
                'start_at': self.start_at,
                'end_at': self.start_at + timedelta(hours=1),
                'status': Appointment.Status.PLANNED,
                'notes': '',
            },
            member_ids=[self.member.id],
        )[0]

    def _login(self, user):
        self.client.force_login(user, backend='apps.accounts.backends.EmailBackend')

    def test_creation_schedules_assignment_and_thirty_minute_reminder(self):
        appointment = self._create_appointment()

        created = Notification.objects.get(
            user=self.member,
            appointment=appointment,
            type=Notification.Type.CREATED,
        )
        reminder = Notification.objects.get(
            user=self.member,
            appointment=appointment,
            type=Notification.Type.REMINDER,
        )
        self.assertLessEqual(created.scheduled_for, timezone.now())
        self.assertEqual(
            reminder.scheduled_for,
            appointment.start_at - timedelta(minutes=30),
        )
        self.assertFalse(Notification.objects.filter(user=self.other_member).exists())

    def test_agency_reminder_delay_and_user_preferences_are_respected(self):
        from apps.core.models import AgencySettings

        agency = AgencySettings.load()
        agency.reminder_minutes = 45
        agency.save()
        self.member.profile.in_app_notifications_enabled = False
        self.member.profile.browser_notifications_enabled = False
        self.member.profile.save(
            update_fields=(
                'in_app_notifications_enabled',
                'browser_notifications_enabled',
                'updated_at',
            )
        )

        appointment = self._create_appointment()
        self.assertFalse(Notification.objects.filter(appointment=appointment).exists())

        self.member.profile.in_app_notifications_enabled = True
        self.member.profile.save(
            update_fields=('in_app_notifications_enabled', 'updated_at')
        )
        self.start_at += timedelta(days=1)
        appointment = self._create_appointment()
        reminder = Notification.objects.get(
            appointment=appointment,
            user=self.member,
            type=Notification.Type.REMINDER,
        )
        self.assertEqual(
            reminder.scheduled_for,
            appointment.start_at - timedelta(minutes=45),
        )

    def test_update_reschedules_reminder_and_cancel_replaces_it_with_alert(self):
        appointment = self._create_appointment()
        moved_start = self.start_at + timedelta(days=1)

        update_appointment(
            actor=self.admin,
            appointment=appointment,
            data={
                'start_at': moved_start,
                'end_at': moved_start + timedelta(hours=1),
            },
        )

        reminder = Notification.objects.get(
            appointment=appointment,
            user=self.member,
            type=Notification.Type.REMINDER,
        )
        self.assertEqual(reminder.scheduled_for, moved_start - timedelta(minutes=30))
        self.assertTrue(
            Notification.objects.filter(
                appointment=appointment,
                user=self.member,
                type=Notification.Type.UPDATED,
            ).exists()
        )

        cancel_appointment(actor=self.admin, appointment=appointment)

        self.assertFalse(
            Notification.objects.filter(
                appointment=appointment,
                type=Notification.Type.REMINDER,
                sent_at__isnull=True,
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                appointment=appointment,
                user=self.member,
                type=Notification.Type.CANCELLED,
            ).exists()
        )

    def test_due_dispatch_is_idempotent(self):
        self._create_appointment()

        self.assertEqual(dispatch_due_notifications(), 1)
        self.assertEqual(dispatch_due_notifications(), 0)
        self.assertEqual(Notification.objects.filter(sent_at__isnull=False).count(), 1)

    def test_api_is_user_scoped_and_supports_read_actions(self):
        appointment = self._create_appointment()
        notification = Notification.objects.get(
            appointment=appointment,
            user=self.member,
            type=Notification.Type.CREATED,
        )

        self._login(self.other_member)
        self.assertEqual(
            self.client.post(reverse('notifications:read', args=(notification.id,))).status_code,
            404,
        )
        self.assertEqual(self.client.get(reverse('notifications:list')).json()['data'], [])

        self._login(self.member)
        response = self.client.get(reverse('notifications:list'), {'unread': 'true'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['unread_count'], 1)

        read_response = self.client.post(
            reverse('notifications:read', args=(notification.id,))
        )
        self.assertEqual(read_response.status_code, 200)
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

        read_all_response = self.client.post(reverse('notifications:read-all'))
        self.assertEqual(read_all_response.status_code, 200)
        self.assertEqual(read_all_response.json()['updated'], 0)
        self.assertFalse(
            self.member.notifications.filter(
                is_read=False,
                scheduled_for__lte=timezone.now(),
            ).exists()
        )

    def test_notifications_page_requires_login_and_shows_unread_count(self):
        self._create_appointment()
        response = self.client.get(reverse('notifications:page'))
        self.assertEqual(response.status_code, 302)

        self._login(self.member)
        response = self.client.get(reverse('notifications:page'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Client meeting')
        self.assertContains(response, 'Tout marquer comme lu')

    def test_notifications_page_and_api_are_paginated(self):
        Notification.objects.bulk_create([
            Notification(
                user=self.member, type=Notification.Type.UPDATED,
                title=f'Notification {index}', message='Message',
                scheduled_for=timezone.now(),
            )
            for index in range(55)
        ])
        self._login(self.member)

        page = self.client.get(reverse('notifications:page'))
        api = self.client.get(reverse('notifications:list'))

        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(page.context['notifications']), 25)
        self.assertEqual(page.context['notification_page'].paginator.num_pages, 3)
        self.assertEqual(len(api.json()['data']), 50)
        self.assertEqual(api.json()['pagination']['pages'], 2)

    def test_push_subscription_api_is_authenticated_and_user_scoped(self):
        url = reverse('notifications:push-subscriptions')
        payload = {
            'endpoint': 'https://push.example.test/subscription/one',
            'keys': {'p256dh': 'browser-public-key', 'auth': 'browser-auth-secret'},
        }
        self.assertEqual(
            self.client.post(url, data=json.dumps(payload), content_type='application/json').status_code,
            401,
        )

        self._login(self.member)
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_USER_AGENT='Notification Test Browser',
        )
        self.assertEqual(response.status_code, 201)
        subscription = PushSubscription.objects.get(endpoint=payload['endpoint'])
        self.assertEqual(subscription.user, self.member)
        self.assertEqual(subscription.user_agent, 'Notification Test Browser')

        invalid = self.client.post(
            url,
            data=json.dumps({**payload, 'endpoint': 'http://insecure.example.test'}),
            content_type='application/json',
        )
        self.assertEqual(invalid.status_code, 400)

        deleted = self.client.delete(
            url,
            data=json.dumps({'endpoint': payload['endpoint']}),
            content_type='application/json',
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(PushSubscription.objects.filter(id=subscription.id).exists())
        self.member.profile.refresh_from_db()
        self.assertFalse(self.member.profile.browser_notifications_enabled)

    def test_service_worker_is_served_from_root_scope_without_cache(self):
        response = self.client.get(reverse('notifications:service-worker'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Service-Worker-Allowed'], '/')
        self.assertIn('no-cache', response['Cache-Control'])
        self.assertContains(response, "self.addEventListener('push'")

    @override_settings(
        VAPID_PUBLIC_KEY='public-vapid-key',
        VAPID_PRIVATE_KEY='private-vapid-key',
        VAPID_SUBJECT='mailto:notifications@example.test',
    )
    @patch('apps.notifications.services.webpush')
    def test_due_push_is_sent_once(self, webpush_mock):
        self.member.profile.browser_notifications_enabled = True
        self.member.profile.save(update_fields=('browser_notifications_enabled', 'updated_at'))
        self.member.push_subscriptions.create(
            endpoint='https://push.example.test/subscription/reminder',
            p256dh='browser-public-key',
            auth='browser-auth-secret',
            user_agent='Test Browser',
        )
        self._create_appointment()

        self.assertEqual(dispatch_due_notifications(), 1)
        self.assertEqual(dispatch_due_notifications(), 0)
        webpush_mock.assert_called_once()
        call = webpush_mock.call_args.kwargs
        self.assertEqual(call['subscription_info']['keys']['auth'], 'browser-auth-secret')
        self.assertEqual(
            call['vapid_claims']['sub'],
            'mailto:notifications@example.test',
        )

    @override_settings(CRON_SECRET='test-cron-secret-value')
    @patch('apps.notifications.views.dispatch_due_notifications', return_value=3)
    def test_scheduler_endpoint_requires_bearer_secret(self, dispatch_mock):
        url = reverse('notifications:send-due-notifications')
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertFalse(dispatch_mock.called)

        response = self.client.get(
            url,
            HTTP_AUTHORIZATION='Bearer test-cron-secret-value',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['processed'], 3)
        dispatch_mock.assert_called_once()
