import json
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.test import Client as Browser, TestCase, override_settings
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
        cls.start_at = (timezone.now() + timedelta(days=10)).replace(
            minute=0, second=0, microsecond=0,
        )

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
            self.client.post(
                reverse('calendar_app:appointment-delete-api', args=(appointment_id,))
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

    def test_assignment_changes_create_precise_audit_entries(self):
        response = self._api_create()
        appointment_id = response.json()['data']['id']

        response = self.client.patch(
            reverse('calendar_app:appointment-detail-api', args=(appointment_id,)),
            data=json.dumps({'member_ids': [self.other_member.id]}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(ActivityLog.objects.filter(
            entity_id=appointment_id, action='appointment_member_assigned',
            new_values__member_id=str(self.other_member.id),
        ).exists())
        self.assertTrue(ActivityLog.objects.filter(
            entity_id=appointment_id, action='appointment_member_unassigned',
            old_values__member_id=str(self.member.id),
        ).exists())

    def test_status_change_creates_precise_audit_entry(self):
        response = self._api_create()
        appointment_id = response.json()['data']['id']

        response = self.client.patch(
            reverse('calendar_app:appointment-detail-api', args=(appointment_id,)),
            data=json.dumps({'status': Appointment.Status.CONFIRMED}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(ActivityLog.objects.filter(
            entity_id=appointment_id, action='appointment_status_changed',
            old_values__status=Appointment.Status.PLANNED,
            new_values__status=Appointment.Status.CONFIRMED,
        ).exists())

    def test_calendar_page_hides_management_controls_from_member(self):
        self._login(self.member)
        member_response = self.client.get(reverse('calendar_app:calendar-page'))
        self.assertEqual(member_response.status_code, 200)
        self.assertNotContains(member_response, 'Nouveau rendez-vous')
        self.assertNotContains(member_response, 'Private Client')
        self.assertNotContains(member_response, 'id="delete-appointment"')
        self.assertContains(member_response, 'data-auto-sync-seconds="10"')

        self._login(self.admin)
        admin_response = self.client.get(reverse('calendar_app:calendar-page'))
        self.assertContains(admin_response, 'Nouveau rendez-vous')
        self.assertContains(admin_response, 'Private Client')
        self.assertContains(admin_response, 'Modifier')
        self.assertContains(admin_response, 'id="delete-appointment"')
        self.assertContains(admin_response, 'Créer un client rapide')

        self._login(self.manager)
        self.assertContains(
            self.client.get(reverse('calendar_app:calendar-page')),
            'id="delete-appointment"',
        )

    def test_postponed_status_is_removed_from_ui_and_api(self):
        self._login(self.admin)
        page = self.client.get(reverse('calendar_app:calendar-page'))
        self.assertNotContains(page, 'Reporté')
        self.assertNotContains(page, 'value="postponed"')

        response = self._api_create(status='postponed')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Appointment.objects.filter(status='postponed').exists())

    def test_admin_and_manager_can_soft_delete_with_complete_audit(self):
        from apps.notifications.models import Notification

        for actor in (self.admin, self.manager):
            with self.subTest(role=actor.profile.role):
                response = self._api_create(
                    title=f'Delete by {actor.profile.role}',
                    start_at=(self.start_at + timedelta(days=actor.pk)).isoformat(),
                    end_at=(self.start_at + timedelta(days=actor.pk, hours=1)).isoformat(),
                )
                appointment_id = response.json()['data']['id']
                appointment = Appointment.objects.get(pk=appointment_id)
                sent = Notification.objects.filter(appointment=appointment).first()
                sent.sent_at = timezone.now()
                sent.save(update_fields=('sent_at',))
                old_member_ids = list(appointment.members.values_list('pk', flat=True))
                self._login(actor)
                deleted = self.client.post(
                    reverse('calendar_app:appointment-delete-api', args=(appointment_id,))
                )
                self.assertEqual(deleted.status_code, 200)
                self.assertEqual(deleted.json()['data'], {'id': appointment_id, 'deleted': True})
                appointment.refresh_from_db()
                self.assertIsNotNone(appointment.deleted_at)
                self.assertEqual(appointment.updated_by, actor)
                self.assertEqual(
                    list(appointment.members.values_list('pk', flat=True)), old_member_ids,
                )
                self.assertTrue(Notification.objects.filter(pk=sent.pk).exists())
                self.assertFalse(Notification.objects.filter(
                    appointment=appointment, sent_at__isnull=True,
                ).exists())
                audit = ActivityLog.objects.get(
                    action='appointment_deleted', entity_id=appointment_id,
                )
                self.assertEqual(audit.user, actor)
                self.assertEqual(audit.old_values['title'], f'Delete by {actor.profile.role}')
                self.assertEqual(audit.old_values['member_ids'], old_member_ids)
                self.assertIsNotNone(audit.new_values['deleted_at'])
                self.assertContains(
                    self.client.get(reverse('audit:history')),
                    'Rendez-vous supprimé',
                )
                self.assertEqual(
                    self.client.get(
                        reverse('calendar_app:appointment-detail-api', args=(appointment_id,))
                    ).status_code,
                    404,
                )

    def test_deleted_appointment_disappears_from_calendar_and_dashboard(self):
        response = self._api_create()
        appointment_id = response.json()['data']['id']
        self.client.post(
            reverse('calendar_app:appointment-delete-api', args=(appointment_id,))
        )
        calendar = self.client.get(reverse('calendar_app:calendar-api'), {
            'start': (self.start_at - timedelta(days=1)).isoformat(),
            'end': (self.start_at + timedelta(days=1)).isoformat(),
        })
        self.assertEqual(calendar.json()['data'], [])
        dashboard = self.client.get(reverse('dashboard'))
        self.assertNotContains(dashboard, 'Private strategy meeting')
        self.assertTrue(Appointment.objects.filter(pk=appointment_id).exists())

    def test_delete_requires_post_csrf_and_an_existing_active_appointment(self):
        response = self._api_create()
        appointment_id = response.json()['data']['id']
        url = reverse('calendar_app:appointment-delete-api', args=(appointment_id,))
        self.assertEqual(self.client.get(url).status_code, 405)

        csrf_browser = Browser(enforce_csrf_checks=True)
        csrf_browser.force_login(self.admin, backend='apps.accounts.backends.EmailBackend')
        self.assertEqual(csrf_browser.post(url).status_code, 403)
        self.assertIsNone(Appointment.objects.get(pk=appointment_id).deleted_at)

        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_deleting_cancelled_occurrence_preserves_other_recurrences(self):
        response = self._api_create(
            recurrence={
                'frequency': 'daily', 'interval_value': 1,
                'end_date': (self.start_at + timedelta(days=2)).date().isoformat(),
            }
        )
        appointment_id = response.json()['data']['id']
        self.client.post(
            reverse('calendar_app:appointment-cancel-api', args=(appointment_id,))
        )
        self.client.post(
            reverse('calendar_app:appointment-delete-api', args=(appointment_id,))
        )
        self.assertEqual(Appointment.objects.filter(deleted_at__isnull=True).count(), 2)
        deleted = Appointment.objects.get(pk=appointment_id)
        self.assertEqual(deleted.status, Appointment.Status.CANCELLED)
        self.assertIsNotNone(deleted.deleted_at)

    def test_stale_edit_and_second_service_delete_cannot_change_deleted_record(self):
        from .services import delete_appointment, update_appointment

        response = self._api_create()
        appointment = Appointment.objects.get(pk=response.json()['data']['id'])
        stale = Appointment.objects.get(pk=appointment.pk)
        delete_appointment(actor=self.admin, appointment=appointment)
        with self.assertRaises(ValidationError):
            delete_appointment(actor=self.manager, appointment=stale)
        with self.assertRaises(ValidationError):
            update_appointment(actor=self.manager, appointment=stale, data={'title': 'Restored'})
        appointment.refresh_from_db()
        self.assertNotEqual(appointment.title, 'Restored')
        self.assertIsNotNone(appointment.deleted_at)


    def test_delete_rolls_back_when_audit_write_fails(self):
        from unittest.mock import patch
        from .services import delete_appointment

        response = self._api_create()
        appointment = Appointment.objects.get(pk=response.json()['data']['id'])
        with patch('apps.calendar_app.services.log_activity', side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):
                delete_appointment(actor=self.admin, appointment=appointment)
        appointment.refresh_from_db()
        self.assertIsNone(appointment.deleted_at)

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


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AutomaticAppointmentStatusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = create_user_account(
            email='automatic-status-admin@example.test', password='automatic-status-password',
            full_name='Automatic Status Admin', role=Profile.Role.ADMIN,
        )
        cls.kind = AppointmentType.objects.create(name='Automatic Status', created_by=cls.admin)
        cls.reference = timezone.now()

    def appointment(self, *, title, status, start_delta, end_delta, deleted=False):
        return Appointment.objects.create(
            title=title, status=status, appointment_type=self.kind,
            start_at=self.reference + start_delta, end_at=self.reference + end_delta,
            created_by=self.admin, updated_by=self.admin,
            deleted_at=self.reference if deleted else None,
        )

    def test_all_status_rules_boundaries_audit_and_idempotency(self):
        from .services import refresh_appointment_statuses

        future = self.appointment(title='Future', status='planned', start_delta=timedelta(minutes=1), end_delta=timedelta(hours=1))
        at_start = self.appointment(title='At start', status='planned', start_delta=timedelta(), end_delta=timedelta(hours=1))
        finished = self.appointment(title='Finished', status='planned', start_delta=-timedelta(hours=2), end_delta=-timedelta(hours=1))
        at_end = self.appointment(title='At end', status='confirmed', start_delta=-timedelta(hours=1), end_delta=timedelta())
        unchanged = {
            status: self.appointment(title=f'Unchanged {status}', status=status, start_delta=-timedelta(hours=2), end_delta=-timedelta(hours=1))
            for status in ('cancelled', 'completed')
        }
        deleted = self.appointment(title='Deleted', status='planned', start_delta=-timedelta(hours=2), end_delta=-timedelta(hours=1), deleted=True)

        self.assertEqual(
            refresh_appointment_statuses(now=self.reference),
            {'confirmed': 1, 'completed': 2, 'total': 3},
        )
        expected = {
            future: 'planned', at_start: 'confirmed', finished: 'completed',
            at_end: 'completed', deleted: 'planned',
            **{appointment: status for status, appointment in unchanged.items()},
        }
        for appointment, status in expected.items():
            appointment.refresh_from_db()
            self.assertEqual(appointment.status, status)
        transitions = ActivityLog.objects.filter(
            action='appointment_status_changed', new_values__automatic=True,
        )
        self.assertEqual(transitions.count(), 3)
        for transition in transitions:
            self.assertIsNone(transition.user_id)
            self.assertEqual(transition.new_values['transition_at'], self.reference.isoformat())
        self.assertEqual(refresh_appointment_statuses(now=self.reference)['total'], 0)
        self.assertEqual(transitions.count(), 3)

    def test_confirmed_future_status_never_moves_back(self):
        from .services import refresh_appointment_statuses

        appointment = self.appointment(title='Future confirmed', status='confirmed', start_delta=timedelta(hours=1), end_delta=timedelta(hours=2))
        self.assertEqual(refresh_appointment_statuses(now=self.reference)['total'], 0)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, 'confirmed')

    def test_calendar_and_dashboard_apply_pending_transitions(self):
        appointment = self.appointment(title='Calendar refresh', status='planned', start_delta=-timedelta(days=1), end_delta=-timedelta(hours=1))
        self.client.force_login(self.admin, backend='apps.accounts.backends.EmailBackend')
        response = self.client.get(reverse('calendar_app:calendar-api'), {
            'start': (self.reference - timedelta(days=2)).isoformat(),
            'end': (self.reference + timedelta(days=2)).isoformat(),
        })
        self.assertEqual(response.status_code, 200)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, 'completed')
        second = self.appointment(title='Dashboard refresh', status='planned', start_delta=-timedelta(days=1), end_delta=-timedelta(hours=1))
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)
        second.refresh_from_db()
        self.assertEqual(second.status, 'completed')
