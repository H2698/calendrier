import json
from datetime import datetime, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Profile
from apps.accounts.services import create_user_account
from apps.audit.models import ActivityLog
from apps.clients.services import create_client

from .models import Appointment, AppointmentType


class CalendarBackendTests(TestCase):
    password = 'A-strong-test-password-482!'

    @classmethod
    def setUpTestData(cls):
        cls.admin = create_user_account(
            email='calendar-admin@agency.test',
            password=cls.password,
            full_name='Calendar Admin',
            role=Profile.Role.ADMIN,
        )
        cls.manager = create_user_account(
            email='calendar-manager@agency.test',
            password=cls.password,
            full_name='Calendar Manager',
            role=Profile.Role.MANAGER,
        )
        cls.member = create_user_account(
            email='calendar-member@agency.test',
            password=cls.password,
            full_name='Assigned Member',
            role=Profile.Role.MEMBER,
            calendar_color='#F97316',
        )
        cls.other_member = create_user_account(
            email='calendar-other@agency.test',
            password=cls.password,
            full_name='Other Member',
            role=Profile.Role.MEMBER,
        )
        cls.appointment_type = AppointmentType.objects.create(
            name='Test Meeting', created_by=cls.admin
        )
        cls.client_record = create_client(
            actor=cls.admin,
            data={
                'name': 'Private Client',
                'phone': '+216 99 123 456',
                'email': 'private@example.com',
                'notes': 'Sensitive client note',
            },
        )
        cls.start_at = timezone.make_aware(datetime(2026, 9, 1, 10, 0))

    def _login(self, user):
        self.client.force_login(user, backend='apps.accounts.backends.EmailBackend')

    def _create_payload(self, **overrides):
        payload = {
            'title': 'Private strategy meeting',
            'description': 'Confidential description',
            'notes': 'Confidential appointment notes',
            'client_id': str(self.client_record.id),
            'appointment_type_id': str(self.appointment_type.id),
            'start_at': self.start_at.isoformat(),
            'end_at': (self.start_at + timedelta(hours=1)).isoformat(),
            'status': Appointment.Status.PLANNED,
            'member_ids': [self.member.id],
        }
        payload.update(overrides)
        return payload

    def _api_create(self, user=None, **overrides):
        self._login(user or self.admin)
        return self.client.post(
            reverse('calendar_app:appointments-api'),
            data=json.dumps(self._create_payload(**overrides)),
            content_type='application/json',
        )

    def test_admin_can_create_multi_assigned_appointment(self):
        response = self._api_create(member_ids=[self.member.id, self.manager.id])

        self.assertEqual(response.status_code, 201)
        appointment = Appointment.objects.get(title='Private strategy meeting')
        self.assertEqual(appointment.members.count(), 2)
        self.assertTrue(
            ActivityLog.objects.filter(
                action='appointment_created', entity_id=appointment.id
            ).exists()
        )

    def test_member_cannot_create_patch_move_or_cancel(self):
        create_response = self._api_create(user=self.admin)
        appointment_id = create_response.json()['data']['id']
        self._login(self.member)

        responses = (
            self.client.post(
                reverse('calendar_app:appointments-api'),
                data=json.dumps(self._create_payload()),
                content_type='application/json',
            ),
            self.client.patch(
                reverse('calendar_app:appointment-detail-api', args=(appointment_id,)),
                data=json.dumps({'title': 'Forbidden'}),
                content_type='application/json',
            ),
            self.client.post(
                reverse('calendar_app:appointment-move-api', args=(appointment_id,)),
                data=json.dumps(
                    {
                        'start_at': (self.start_at + timedelta(hours=3)).isoformat(),
                        'end_at': (self.start_at + timedelta(hours=4)).isoformat(),
                    }
                ),
                content_type='application/json',
            ),
            self.client.post(
                reverse('calendar_app:appointment-cancel-api', args=(appointment_id,))
            ),
        )

        for response in responses:
            self.assertEqual(response.status_code, 403)

    def test_conflict_warns_but_can_be_forced(self):
        first = self._api_create()
        self.assertEqual(first.status_code, 201)

        warning = self._api_create(
            title='Overlapping meeting',
            start_at=(self.start_at + timedelta(minutes=30)).isoformat(),
            end_at=(self.start_at + timedelta(hours=1, minutes=30)).isoformat(),
        )
        self.assertEqual(warning.status_code, 409)
        self.assertEqual(warning.json()['error'], 'appointment_conflict')
        self.assertEqual(Appointment.objects.count(), 1)

        forced = self._api_create(
            title='Overlapping meeting',
            start_at=(self.start_at + timedelta(minutes=30)).isoformat(),
            end_at=(self.start_at + timedelta(hours=1, minutes=30)).isoformat(),
            force_conflicts=True,
        )
        self.assertEqual(forced.status_code, 201)
        self.assertEqual(forced.json()['conflicts'], 1)

    def test_private_fields_only_for_assigned_member(self):
        response = self._api_create()
        appointment_id = response.json()['data']['id']

        self._login(self.member)
        assigned = self.client.get(
            reverse('calendar_app:appointment-detail-api', args=(appointment_id,))
        ).json()['data']
        self.assertEqual(assigned['client']['phone'], '+216 99 123 456')
        self.assertIn('notes', assigned)

        self._login(self.other_member)
        unassigned = self.client.get(
            reverse('calendar_app:appointment-detail-api', args=(appointment_id,))
        ).json()['data']
        self.assertEqual(unassigned['title'], 'Rendez-vous agence')
        self.assertNotIn('client', unassigned)
        self.assertNotIn('notes', unassigned)
        self.assertNotIn('description', unassigned)

    def test_calendar_filters_visible_period(self):
        self._api_create()
        self._api_create(
            title='Later meeting',
            start_at=(self.start_at + timedelta(days=5)).isoformat(),
            end_at=(self.start_at + timedelta(days=5, hours=1)).isoformat(),
        )
        self._login(self.admin)

        response = self.client.get(
            reverse('calendar_app:calendar-api'),
            {
                'start': (self.start_at - timedelta(days=1)).isoformat(),
                'end': (self.start_at + timedelta(days=1)).isoformat(),
                'member': self.member.id,
                'status': Appointment.Status.PLANNED,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['data']), 1)

    def test_move_and_cancel_create_precise_audit_entries(self):
        response = self._api_create()
        appointment_id = response.json()['data']['id']
        self._login(self.manager)

        move_response = self.client.post(
            reverse('calendar_app:appointment-move-api', args=(appointment_id,)),
            data=json.dumps(
                {
                    'start_at': (self.start_at + timedelta(hours=2)).isoformat(),
                    'end_at': (self.start_at + timedelta(hours=3)).isoformat(),
                }
            ),
            content_type='application/json',
        )
        cancel_response = self.client.post(
            reverse('calendar_app:appointment-cancel-api', args=(appointment_id,))
        )

        self.assertEqual(move_response.status_code, 200)
        self.assertEqual(cancel_response.status_code, 200)
        self.assertTrue(
            ActivityLog.objects.filter(
                entity_id=appointment_id, action='appointment_moved'
            ).exists()
        )
        self.assertTrue(
            ActivityLog.objects.filter(
                entity_id=appointment_id, action='appointment_cancelled'
            ).exists()
        )

    def test_activity_api_is_for_admin_and_manager_only(self):
        self._api_create()
        for user in (self.admin, self.manager):
            self._login(user)
            response = self.client.get(reverse('audit:activity-api'))
            self.assertEqual(response.status_code, 200)
            self.assertGreaterEqual(response.json()['pagination']['count'], 1)

        self._login(self.member)
        self.assertEqual(
            self.client.get(reverse('audit:activity-api')).status_code,
            403,
        )

    def test_calendar_page_hides_management_controls_from_member(self):
        self._login(self.member)
        member_response = self.client.get(reverse('calendar_app:calendar-page'))
        self.assertEqual(member_response.status_code, 200)
        self.assertNotContains(member_response, 'Nouveau rendez-vous')
        self.assertNotContains(member_response, 'Private Client')
        self.assertContains(member_response, 'data-auto-sync-seconds="10"')

        self._login(self.admin)
        admin_response = self.client.get(reverse('calendar_app:calendar-page'))
        self.assertContains(admin_response, 'Nouveau rendez-vous')
        self.assertContains(admin_response, 'Private Client')

    def test_calendar_sync_payload_keeps_unassigned_member_data_private(self):
        self._api_create()
        self._login(self.other_member)

        response = self.client.get(
            reverse('calendar_app:calendar-api'),
            {
                'start': (self.start_at - timedelta(days=1)).isoformat(),
                'end': (self.start_at + timedelta(days=1)).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        item = response.json()['data'][0]
        self.assertEqual(item['title'], 'Rendez-vous agence')
        self.assertNotIn('client', item)
        self.assertNotIn('description', item)
        self.assertNotIn('notes', item)

    def test_daily_recurrence_creates_real_editable_occurrences(self):
        response = self._api_create(
            recurrence={
                'frequency': 'daily',
                'interval_value': 1,
                'end_date': (self.start_at + timedelta(days=2)).date().isoformat(),
            }
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['occurrence_count'], 3)
        appointments = list(Appointment.objects.order_by('start_at'))
        self.assertEqual(len(appointments), 3)
        self.assertEqual(len({item.recurrence_series_id for item in appointments}), 1)

        self._login(self.manager)
        edited = appointments[1]
        patch_response = self.client.patch(
            reverse('calendar_app:appointment-detail-api', args=(edited.id,)),
            data=json.dumps({'title': 'Occurrence modifiée'}),
            content_type='application/json',
        )
        self.assertEqual(patch_response.status_code, 200)
        appointments[0].refresh_from_db()
        edited.refresh_from_db()
        self.assertEqual(appointments[0].title, 'Private strategy meeting')
        self.assertEqual(edited.title, 'Occurrence modifiée')
