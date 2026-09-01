from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import Client as Browser, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Profile
from apps.accounts.services import create_user_account, delete_team_member
from apps.audit.models import ActivityLog
from apps.notifications.models import Notification
from apps.notifications.services import schedule_report_notifications

from .models import Appointment, AppointmentMember, AppointmentReport, AppointmentType
from .services import refresh_appointment_statuses, submit_appointment_report, update_appointment


class AppointmentReportTests(TestCase):
    password = 'A-strong-test-password-482!'

    @classmethod
    def setUpTestData(cls):
        cls.admin = create_user_account(
            email='report-admin@agency.test', password=cls.password,
            full_name='Report Admin', role=Profile.Role.ADMIN,
        )
        cls.manager = create_user_account(
            email='report-manager@agency.test', password=cls.password,
            full_name='Report Manager', role=Profile.Role.MANAGER,
        )
        cls.member = create_user_account(
            email='report-member@agency.test', password=cls.password,
            full_name='Report Member', role=Profile.Role.MEMBER,
        )
        cls.second_member = create_user_account(
            email='report-second@agency.test', password=cls.password,
            full_name='Second Reporter', role=Profile.Role.MEMBER,
        )
        cls.outsider = create_user_account(
            email='report-outsider@agency.test', password=cls.password,
            full_name='Report Outsider', role=Profile.Role.MEMBER,
        )
        cls.appointment_type = AppointmentType.objects.create(
            name='Report Meeting', created_by=cls.admin,
        )

    def setUp(self):
        end_at = timezone.now() - timedelta(hours=1)
        self.appointment = Appointment.objects.create(
            appointment_type=self.appointment_type,
            title='Réunion terminée à rapporter',
            start_at=end_at - timedelta(hours=1), end_at=end_at,
            status=Appointment.Status.COMPLETED,
            created_by=self.admin, updated_by=self.admin,
        )
        AppointmentMember.objects.bulk_create([
            AppointmentMember(appointment=self.appointment, user=self.member),
            AppointmentMember(appointment=self.appointment, user=self.second_member),
        ])
        schedule_report_notifications(self.appointment)

    def _login(self, user):
        self.client.force_login(user, backend='apps.accounts.backends.EmailBackend')

    @property
    def url(self):
        return reverse('calendar_app:appointment-reports', args=(self.appointment.pk,))

    def test_assigned_member_submits_one_final_report_with_audit(self):
        self._login(self.member)
        self.assertContains(self.client.get(self.url), 'Envoyer définitivement')

        response = self.client.post(self.url, {'content': 'Décisions et actions validées.'})

        self.assertRedirects(response, self.url)
        report = AppointmentReport.objects.get(
            appointment=self.appointment, author=self.member,
        )
        self.assertEqual(report.author_name, 'Report Member')
        self.assertEqual(report.content, 'Décisions et actions validées.')
        report_notification = Notification.objects.get(
            appointment=self.appointment, user=self.member,
            type=Notification.Type.REPORT_REQUIRED,
        )
        self.assertTrue(report_notification.is_read)
        self.assertIsNotNone(report_notification.sent_at)
        audit = ActivityLog.objects.get(
            action='appointment_report_submitted', entity_id=report.pk,
        )
        self.assertTrue(audit.new_values['immutable'])
        self.assertEqual(audit.new_values['content_length'], len(report.content))
        self.assertNotIn(report.content, str(audit.new_values))

    def test_report_cannot_be_submitted_twice_or_modified(self):
        report = submit_appointment_report(
            actor=self.member, appointment=self.appointment,
            content='Premier rapport définitif.',
        )
        self._login(self.member)
        self.assertEqual(
            self.client.post(self.url, {'content': 'Deuxième rapport interdit.'}).status_code,
            403,
        )
        report.content = 'Modification interdite.'
        with self.assertRaisesMessage(
            ValidationError, 'Un rapport envoyé ne peut pas être modifié.',
        ):
            report.save()
        report.refresh_from_db()
        self.assertEqual(report.content, 'Premier rapport définitif.')

    def test_visibility_is_private_for_members_and_complete_for_managers(self):
        submit_appointment_report(
            actor=self.member, appointment=self.appointment,
            content='Contenu privé du premier membre.',
        )
        submit_appointment_report(
            actor=self.second_member, appointment=self.appointment,
            content='Contenu privé du second membre.',
        )
        AppointmentMember.objects.create(appointment=self.appointment, user=self.admin)
        schedule_report_notifications(self.appointment)

        self._login(self.member)
        member_page = self.client.get(self.url)
        self.assertContains(member_page, 'Contenu privé du premier membre.')
        self.assertNotContains(member_page, 'Contenu privé du second membre.')

        for manager in (self.admin, self.manager):
            with self.subTest(role=manager.profile.role):
                self._login(manager)
                page = self.client.get(self.url)
                self.assertContains(page, 'Contenu privé du premier membre.')
                self.assertContains(page, 'Contenu privé du second membre.')
                self.assertContains(page, 'Report Admin')

        self._login(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_report_is_only_available_after_completion_and_requires_assignment(self):
        self.appointment.status = Appointment.Status.PLANNED
        self.appointment.start_at = timezone.now() + timedelta(days=1)
        self.appointment.end_at = self.appointment.start_at + timedelta(hours=1)
        self.appointment.save(update_fields=('status', 'start_at', 'end_at'))
        self._login(self.member)
        page = self.client.get(self.url)
        self.assertContains(page, 'sera disponible lorsque le rendez-vous sera terminé')
        self.assertEqual(
            self.client.post(self.url, {'content': 'Rapport envoyé trop tôt.'}).status_code,
            403,
        )

        self._login(self.outsider)
        self.assertEqual(self.client.post(
            self.url, {'content': 'Rapport sans affectation.'},
        ).status_code, 403)

    def test_automatic_completion_creates_report_request(self):
        self.appointment.status = Appointment.Status.CONFIRMED
        self.appointment.save(update_fields=('status',))
        Notification.objects.filter(
            appointment=self.appointment, type=Notification.Type.REPORT_REQUIRED,
        ).delete()

        result = refresh_appointment_statuses(now=timezone.now())

        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, Appointment.Status.COMPLETED)
        self.assertEqual(result['completed'], 1)
        self.assertEqual(Notification.objects.filter(
            appointment=self.appointment, type=Notification.Type.REPORT_REQUIRED,
        ).count(), 2)

    def test_assignment_and_status_changes_clean_obsolete_report_requests(self):
        self.assertTrue(Notification.objects.filter(
            appointment=self.appointment, user=self.member,
            type=Notification.Type.REPORT_REQUIRED,
        ).exists())
        update_appointment(
            actor=self.manager, appointment=self.appointment,
            data={}, member_ids=[self.second_member.pk], force_conflicts=True,
        )
        self.assertFalse(Notification.objects.filter(
            appointment=self.appointment, user=self.member,
            type=Notification.Type.REPORT_REQUIRED,
        ).exists())

        future_start = timezone.now() + timedelta(days=2)
        update_appointment(
            actor=self.manager, appointment=self.appointment,
            data={
                'status': Appointment.Status.PLANNED,
                'start_at': future_start,
                'end_at': future_start + timedelta(hours=1),
            },
        )
        self.assertFalse(Notification.objects.filter(
            appointment=self.appointment, type=Notification.Type.REPORT_REQUIRED,
        ).exists())

    def test_dashboard_shows_pending_report_then_removes_action(self):
        self._login(self.member)
        dashboard = self.client.get(reverse('dashboard'))
        self.assertContains(dashboard, '1 rapport à rédiger')
        self.assertContains(dashboard, self.url)

        submit_appointment_report(
            actor=self.member, appointment=self.appointment,
            content='Compte rendu envoyé depuis le tableau de bord.',
        )
        dashboard = self.client.get(reverse('dashboard'))
        self.assertNotContains(dashboard, 'rapport à rédiger')

    def test_report_snapshot_survives_permanent_author_deletion(self):
        report = submit_appointment_report(
            actor=self.member, appointment=self.appointment,
            content='Rapport conservé après suppression du compte.',
        )

        delete_team_member(actor=self.admin, user=self.member)

        report.refresh_from_db()
        self.assertIsNone(report.author)
        self.assertEqual(report.author_name, 'Report Member')
        self.assertEqual(report.author_email, 'report-member@agency.test')
        self.assertEqual(report.content, 'Rapport conservé après suppression du compte.')

    def test_report_submission_is_csrf_protected(self):
        browser = Browser(enforce_csrf_checks=True)
        browser.force_login(self.member, backend='apps.accounts.backends.EmailBackend')
        self.assertEqual(
            browser.post(self.url, {'content': 'Tentative sans jeton CSRF.'}).status_code,
            403,
        )
        self.assertFalse(AppointmentReport.objects.filter(
            appointment=self.appointment, author=self.member,
        ).exists())
