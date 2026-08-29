from datetime import timedelta

from django.test import TestCase
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

from .models import Notification
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
