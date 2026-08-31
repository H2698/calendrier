from django.contrib.auth.models import AnonymousUser
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from .models import Profile
from .permissions import role_required
from .services import create_user_account, set_account_active


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AuthenticationTests(TestCase):
    password = 'A-strong-test-password-482!'

    @classmethod
    def setUpTestData(cls):
        cls.users = {
            role: create_user_account(
                email=f'{role}@agency.test',
                password=cls.password,
                full_name=f'{role.title()} User',
                role=role,
            )
            for role in Profile.Role.values
        }

    def test_admin_manager_and_member_can_login_with_email(self):
        for role, user in self.users.items():
            with self.subTest(role=role):
                response = self.client.post(
                    reverse('accounts:login'),
                    {
                        'username': user.email.upper(),
                        'password': self.password,
                    },
                )
                self.assertRedirects(response, reverse('dashboard'))
                self.assertEqual(
                    int(self.client.session['_auth_user_id']),
                    user.pk,
                )
                self.client.logout()

    def test_disabled_user_cannot_login(self):
        user = self.users[Profile.Role.MEMBER]
        set_account_active(user=user, is_active=False)

        response = self.client.post(
            reverse('accounts:login'),
            {'username': user.email, 'password': self.password},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_disabling_user_ends_existing_session(self):
        user = self.users[Profile.Role.MANAGER]
        self.client.force_login(user, backend='apps.accounts.backends.EmailBackend')
        set_account_active(user=user, is_active=False)

        response = self.client.get(reverse('dashboard'))

        self.assertRedirects(response, reverse('accounts:login'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_dashboard_action_depends_on_role(self):
        member = self.users[Profile.Role.MEMBER]
        shortcut = f"{reverse('calendar_app:calendar-page')}?new=1"
        for role in (Profile.Role.ADMIN, Profile.Role.MANAGER):
            with self.subTest(role=role):
                self.client.force_login(self.users[role], backend='apps.accounts.backends.EmailBackend')
                response = self.client.get(reverse('dashboard'))
                self.assertContains(
                    response,
                    f'<a class="button primary" href="{shortcut}">+ Nouveau rendez-vous</a>',
                    html=True,
                )
                self.assertNotContains(response, 'Disponible dans la phase Calendrier')
                calendar_page = self.client.get(shortcut)
                self.assertEqual(calendar_page.status_code, 200)
                self.assertContains(calendar_page, 'id="appointment-create-form"')

        self.client.force_login(member, backend='apps.accounts.backends.EmailBackend')
        response = self.client.get(reverse('dashboard'))
        self.assertNotContains(response, 'Nouveau rendez-vous')
        self.assertNotContains(
            self.client.get(shortcut), 'id="appointment-create-form"'
        )

    def test_authenticated_layout_contains_accessible_mobile_navigation(self):
        self.client.force_login(
            self.users[Profile.Role.MEMBER],
            backend='apps.accounts.backends.EmailBackend',
        )
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'class="mobile-menu-toggle"')
        self.assertContains(response, 'aria-controls="main-navigation"')
        self.assertContains(response, 'static/js/app.js')

    def test_password_reset_sends_email_for_active_user(self):
        user = self.users[Profile.Role.MEMBER]

        response = self.client.post(
            reverse('accounts:password_reset'),
            {'email': user.email},
        )

        self.assertRedirects(response, reverse('accounts:password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/reset/', mail.outbox[0].body)

    def test_duplicate_email_is_rejected(self):
        existing = self.users[Profile.Role.ADMIN]

        with self.assertRaises(ValidationError):
            create_user_account(
                email=existing.email.upper(),
                password=self.password,
                full_name='Duplicate User',
            )

    def test_login_is_rate_limited_after_repeated_failures(self):
        user = self.users[Profile.Role.MEMBER]
        for attempt in range(5):
            response = self.client.post(
                reverse('accounts:login'),
                {'username': user.email, 'password': 'wrong-password'},
                REMOTE_ADDR='203.0.113.10',
            )
            self.assertEqual(response.status_code, 429 if attempt == 4 else 200)

        blocked = self.client.post(
            reverse('accounts:login'),
            {'username': user.email, 'password': self.password},
            REMOTE_ADDR='203.0.113.10',
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertNotIn('_auth_user_id', self.client.session)

        different_address = self.client.post(
            reverse('accounts:login'),
            {'username': user.email, 'password': self.password},
            REMOTE_ADDR='203.0.113.11',
        )
        self.assertRedirects(different_address, reverse('dashboard'))


class PermissionTests(TestCase):
    password = 'A-strong-test-password-482!'

    @classmethod
    def setUpTestData(cls):
        cls.admin = create_user_account(
            email='permission-admin@agency.test',
            password=cls.password,
            full_name='Permission Admin',
            role=Profile.Role.ADMIN,
        )
        cls.member = create_user_account(
            email='permission-member@agency.test',
            password=cls.password,
            full_name='Permission Member',
            role=Profile.Role.MEMBER,
        )

    def test_role_decorator_allows_expected_role(self):
        @role_required(Profile.Role.ADMIN)
        def protected_view(request):
            return HttpResponse('ok')

        request = RequestFactory().get('/protected/')
        request.user = self.admin

        self.assertEqual(protected_view(request).status_code, 200)

    def test_role_decorator_rejects_member_and_anonymous(self):
        @role_required(Profile.Role.ADMIN)
        def protected_view(request):
            return HttpResponse('ok')

        request = RequestFactory().get('/protected/')
        for user in (self.member, AnonymousUser()):
            request.user = user
            with self.subTest(user=user):
                with self.assertRaises(PermissionDenied):
                    protected_view(request)


class TeamManagementTests(TestCase):
    password = 'A-strong-test-password-482!'

    @classmethod
    def setUpTestData(cls):
        cls.admin = create_user_account(email='team-admin@test.com', password=cls.password, full_name='Team Admin', role=Profile.Role.ADMIN)
        cls.manager = create_user_account(email='team-manager@test.com', password=cls.password, full_name='Team Manager', role=Profile.Role.MANAGER)
        cls.member = create_user_account(email='team-member@test.com', password=cls.password, full_name='Team Member', role=Profile.Role.MEMBER)

    def login(self, user):
        self.client.force_login(user, backend='apps.accounts.backends.EmailBackend')

    def test_admin_creates_and_updates_member(self):
        import json
        from apps.audit.models import ActivityLog
        self.login(self.admin)
        response = self.client.post(reverse('accounts:team-create-api'), data=json.dumps({'email':'new-member@test.com','password':self.password,'full_name':'New Member','role':'member','calendar_color':'#22C55E'}), content_type='application/json')
        self.assertEqual(response.status_code, 201)
        user_id = response.json()['data']['id']
        patched = self.client.patch(reverse('accounts:team-detail-api', args=(user_id,)), data=json.dumps({'role':'manager','is_active':False}), content_type='application/json')
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()['data']['role'], 'manager')
        self.assertFalse(patched.json()['data']['is_active'])
        self.assertTrue(ActivityLog.objects.filter(
            action='user_created', entity_id=user_id, user=self.admin
        ).exists())
        self.assertTrue(ActivityLog.objects.filter(
            action='user_updated', entity_id=user_id, user=self.admin
        ).exists())
        self.assertTrue(ActivityLog.objects.filter(
            action='user_disabled', entity_id=user_id, user=self.admin
        ).exists())

    def test_manager_can_view_but_cannot_create(self):
        import json
        self.login(self.manager)
        self.assertEqual(self.client.get(reverse('accounts:team-api')).status_code, 200)
        self.assertEqual(self.client.post(reverse('accounts:team-create-api'), data=json.dumps({'email':'x@test.com'}), content_type='application/json').status_code, 403)

    def test_member_profile_page_is_viewable_by_manager_and_editable_by_admin(self):
        self.login(self.manager)
        page = self.client.get(
            reverse('accounts:team-member', args=(self.member.id,))
        )
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'Enregistrer')

        self.login(self.admin)
        response = self.client.post(
            reverse('accounts:team-member', args=(self.member.id,)),
            {
                'full_name': 'Member Updated', 'email': self.member.email,
                'role': Profile.Role.MANAGER, 'calendar_color': '#334455',
                'is_active': 'on',
            },
        )
        self.assertRedirects(
            response, reverse('accounts:team-member', args=(self.member.id,))
        )
        self.member.profile.refresh_from_db()
        self.assertEqual(self.member.profile.role, Profile.Role.MANAGER)
        self.assertEqual(self.member.profile.calendar_color, '#334455')

    def test_member_cannot_open_member_profile(self):
        self.login(self.member)
        self.assertEqual(
            self.client.get(
                reverse('accounts:team-member', args=(self.member.id,))
            ).status_code,
            403,
        )

    def test_member_cannot_access_team(self):
        self.login(self.member)
        self.assertEqual(self.client.get(reverse('accounts:team')).status_code, 403)
        self.assertEqual(self.client.get(reverse('accounts:team-api')).status_code, 403)


class TeamDeletionTests(TestCase):
    password = 'A-strong-test-password-482!'

    @classmethod
    def setUpTestData(cls):
        cls.admin = create_user_account(
            email='delete-admin@test.com', password=cls.password,
            full_name='Delete Admin', role=Profile.Role.ADMIN,
        )
        cls.manager = create_user_account(
            email='delete-manager@test.com', password=cls.password,
            full_name='Delete Manager', role=Profile.Role.MANAGER,
        )
        cls.member = create_user_account(
            email='delete-member@test.com', password=cls.password,
            full_name='Delete Member', role=Profile.Role.MEMBER,
        )

    def login(self, user, client=None):
        (client or self.client).force_login(
            user, backend='apps.accounts.backends.EmailBackend'
        )

    def delete_url(self, user=None):
        return reverse('accounts:team-member-delete', args=((user or self.member).pk,))

    def test_admin_and_manager_can_delete_with_audit(self):
        from django.contrib.auth import get_user_model
        from apps.audit.models import ActivityLog

        for actor in (self.admin, self.manager):
            with self.subTest(role=actor.profile.role):
                target = create_user_account(
                    email=f'target-{actor.pk}@test.com', password=self.password,
                    full_name='Target Member',
                )
                self.login(actor)
                response = self.client.post(self.delete_url(target), {'confirm': 'yes'})
                self.assertRedirects(response, reverse('accounts:team'))
                self.assertFalse(get_user_model().objects.filter(pk=target.pk).exists())
                self.assertFalse(Profile.objects.filter(user_id=target.pk).exists())
                log = ActivityLog.objects.get(action='user_permanently_deleted', entity_id=target.pk)
                self.assertEqual(log.user, actor)
                self.assertEqual(log.actor_snapshot['full_name'], actor.profile.full_name)
                self.assertEqual(log.old_values['email'], target.email)
                self.assertTrue(log.old_values['is_active'])
                self.assertTrue(log.new_values['permanently_deleted'])
                self.assertIsNotNone(log.new_values['deleted_at'])
                self.assertNotIn(self.password, str(log.old_values))

    def test_delete_buttons_are_visible_to_admin_and_manager_only_for_allowed_targets(self):
        for actor in (self.admin, self.manager):
            self.login(actor)
            page = self.client.get(reverse('accounts:team'))
            self.assertContains(page, self.delete_url())
            self.assertNotContains(page, self.delete_url(self.admin))
            self.assertNotContains(page, self.delete_url(actor))
            detail = self.client.get(reverse('accounts:team-member', args=(self.member.pk,)))
            self.assertContains(detail, self.delete_url())

    def test_get_missing_confirmation_and_unsupported_methods_never_delete(self):
        self.login(self.admin)
        self.assertContains(self.client.get(self.delete_url()), 'Confirmer la suppression')
        self.assertEqual(self.client.post(self.delete_url()).status_code, 400)
        self.assertEqual(self.client.delete(self.delete_url()).status_code, 405)
        self.member.profile.refresh_from_db()
        self.assertIsNone(self.member.profile.deleted_at)

    def test_post_requires_csrf(self):
        from django.test import Client

        browser = Client(enforce_csrf_checks=True)
        self.login(self.admin, browser)
        self.assertEqual(browser.post(self.delete_url(), {'confirm': 'yes'}).status_code, 403)
        self.member.profile.refresh_from_db()
        self.assertIsNone(self.member.profile.deleted_at)

    def test_member_anonymous_self_and_admin_targets_are_denied(self):
        self.assertEqual(self.client.post(self.delete_url(), {'confirm': 'yes'}).status_code, 302)
        self.login(self.member)
        self.assertEqual(self.client.post(self.delete_url(self.manager), {'confirm': 'yes'}).status_code, 403)
        for actor in (self.admin, self.manager):
            self.login(actor)
            for target in (actor, self.admin):
                self.assertEqual(self.client.post(self.delete_url(target), {'confirm': 'yes'}).status_code, 403)

    def test_service_cannot_bypass_role_or_superuser_protection(self):
        from apps.accounts.services import delete_team_member

        with self.assertRaises(PermissionDenied):
            delete_team_member(actor=self.member, user=self.manager)
        self.member.is_superuser = True
        self.member.save(update_fields=('is_superuser',))
        with self.assertRaises(PermissionDenied):
            delete_team_member(actor=self.manager, user=self.member)

    def test_deleted_member_disappears_from_team_and_cannot_be_edited(self):
        self.login(self.admin)
        self.client.post(self.delete_url(), {'confirm': 'yes'})
        self.assertNotContains(self.client.get(reverse('accounts:team')), self.member.email)
        ids = [item['id'] for item in self.client.get(reverse('accounts:team-api')).json()['data']]
        self.assertNotIn(self.member.pk, ids)
        for name in ('accounts:team-member', 'accounts:team-detail-api', 'accounts:team-member-delete'):
            self.assertEqual(self.client.get(reverse(name, args=(self.member.pk,))).status_code, 404)
        self.assertEqual(self.client.post(self.delete_url(), {'confirm': 'yes'}).status_code, 404)
        self.assertEqual(self.client.patch(
            reverse('accounts:team-detail-api', args=(self.member.pk,)),
            data='{"is_active": true}', content_type='application/json',
        ).status_code, 404)

    def test_existing_session_and_new_login_are_blocked(self):
        from django.test import Client

        member_browser = Client()
        self.login(self.member, member_browser)
        self.login(self.manager)
        self.client.post(self.delete_url(), {'confirm': 'yes'})
        self.assertRedirects(member_browser.get(reverse('dashboard')), reverse('accounts:login'))
        self.assertNotIn('_auth_user_id', member_browser.session)
        member_browser.post(reverse('accounts:login'), {
            'username': self.member.email, 'password': self.password,
        })
        self.assertNotIn('_auth_user_id', member_browser.session)

    def test_stale_profile_cannot_reactivate_deleted_member(self):
        from .services import update_user_account

        # Cache the old profile before another request deletes the member.
        self.assertIsNone(self.member.profile.deleted_at)
        self.login(self.admin)
        self.client.post(self.delete_url(), {'confirm': 'yes'})
        with self.assertRaises(ValidationError):
            update_user_account(actor=self.admin, user=self.member, data={'is_active': True})
        with self.assertRaises(ValidationError):
            set_account_active(user=self.member, is_active=True, actor=self.admin)
        from django.contrib.auth import get_user_model
        self.assertFalse(get_user_model().objects.filter(pk=self.member.pk).exists())

    def test_appointments_clients_and_history_survive_with_assignments_traced(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.audit.models import ActivityLog
        from apps.audit.services import log_activity
        from apps.calendar_app.models import Appointment, AppointmentType
        from apps.clients.services import create_client

        client_record = create_client(actor=self.member, data={'name': 'Retained Client'})
        appointment = Appointment.objects.create(
            client=client_record,
            appointment_type=AppointmentType.objects.first(), title='Retained Meeting',
            start_at=timezone.now(), end_at=timezone.now() + timedelta(hours=1),
            created_by=self.member, updated_by=self.member,
        )
        appointment.members.add(self.member, self.admin)
        old_log = log_activity(
            actor=self.member, action='appointment_created', entity_type='appointment',
            entity_id=appointment.pk,
        )
        self.login(self.manager)
        self.client.post(self.delete_url(), {'confirm': 'yes'})
        appointment.refresh_from_db()
        client_record.refresh_from_db()
        self.assertIsNone(appointment.created_by_id)
        self.assertIsNone(appointment.updated_by_id)
        self.assertIsNone(client_record.created_by_id)
        self.assertFalse(appointment.members.filter(pk=self.member.pk).exists())
        self.assertTrue(appointment.members.filter(pk=self.admin.pk).exists())
        old_log.refresh_from_db()
        self.assertIsNone(old_log.user_id)
        self.assertEqual(old_log.actor_snapshot['id'], str(self.member.pk))
        self.assertEqual(old_log.actor_name, self.member.profile.full_name)
        deletion = ActivityLog.objects.get(action='user_permanently_deleted', entity_id=self.member.pk)
        self.assertEqual(deletion.old_values['created_clients'], [str(client_record.pk)])
        self.assertEqual(deletion.old_values['created_appointments'], [str(appointment.pk)])
        self.assertEqual(deletion.old_values['assigned_appointments'], [
            {'id': str(appointment.pk), 'title': appointment.title},
        ])
        self.assertTrue(ActivityLog.objects.filter(
            action='appointment_member_unassigned', entity_id=appointment.pk,
            old_values__member__id=str(self.member.pk),
        ).exists())
        self.assertContains(self.client.get(reverse('audit:history')), self.member.profile.full_name)
        from apps.clients.views import _client_payload
        self.assertIsNone(_client_payload(client_record)['created_by'])
        from apps.notifications.services import schedule_appointment_notifications
        from apps.notifications.models import Notification
        schedule_appointment_notifications(appointment)
        self.assertFalse(Notification.objects.filter(appointment=appointment, user=self.member).exists())

    def test_deleted_member_receives_no_push(self):
        from unittest.mock import patch
        from django.utils import timezone
        from apps.notifications.models import Notification
        from apps.notifications.services import dispatch_due_notifications

        self.member.profile.browser_notifications_enabled = True
        self.member.profile.save()
        Notification.objects.create(
            user=self.member, type=Notification.Type.REMINDER,
            title='Reminder', message='Message', scheduled_for=timezone.now(),
        )
        self.login(self.admin)
        self.client.post(self.delete_url(), {'confirm': 'yes'})
        with patch('apps.notifications.services.webpush') as webpush:
            dispatch_due_notifications()
            webpush.assert_not_called()
        self.assertFalse(Notification.objects.filter(user_id=self.member.pk).exists())
        self.assertFalse(Profile.objects.filter(user_id=self.member.pk).exists())

    def test_deleted_email_can_be_reused_without_inheriting_old_identity(self):
        from apps.audit.models import ActivityLog
        from django.contrib.auth import get_user_model

        self.login(self.admin)
        self.client.post(self.delete_url(), {'confirm': 'yes'})
        response = self.client.post(reverse('accounts:team'), {
            'email': self.member.email.upper(), 'password': self.password,
            'full_name': 'New Member', 'role': 'member', 'calendar_color': '#123456',
        })
        self.assertRedirects(response, reverse('accounts:team'))
        replacement = get_user_model().objects.get(email=self.member.email)
        self.assertNotEqual(replacement.pk, self.member.pk)
        self.assertTrue(replacement.check_password(self.password))
        self.assertFalse(replacement.appointments.exists())
        self.assertTrue(ActivityLog.objects.filter(
            action='user_permanently_deleted', entity_id=self.member.pk,
        ).exists())

    def test_legacy_archived_account_requires_confirmation_before_permanent_deletion(self):
        from django.contrib.auth import get_user_model
        from django.utils import timezone

        self.member.profile.deleted_at = timezone.now()
        self.member.profile.is_active = False
        self.member.profile.save()
        self.member.is_active = False
        self.member.save()
        self.login(self.admin)
        page = self.client.get(reverse('accounts:team'))
        self.assertContains(page, 'Anciens comptes archivés')
        self.assertContains(page, self.delete_url())
        self.assertNotIn(self.member.pk, [
            item['id'] for item in self.client.get(reverse('accounts:team-api')).json()['data']
        ])
        self.assertContains(self.client.get(self.delete_url()), 'irréversible')
        self.assertTrue(get_user_model().objects.filter(pk=self.member.pk).exists())
        self.assertRedirects(
            self.client.post(self.delete_url(), {'confirm': 'yes'}), reverse('accounts:team'),
        )
        self.assertFalse(get_user_model().objects.filter(pk=self.member.pk).exists())

    def test_duplicate_email_displays_form_error_for_active_and_archived_members(self):
        from django.contrib.auth import get_user_model
        from django.utils import timezone

        self.login(self.admin)
        for archived_at in (None, timezone.now()):
            with self.subTest(archived=bool(archived_at)):
                Profile.objects.filter(user_id=self.member.pk).update(deleted_at=archived_at)
                response = self.client.post(reverse('accounts:team'), {
                    'email': self.member.email.upper(), 'password': self.password,
                    'full_name': 'Duplicate', 'role': 'member', 'calendar_color': '#123456',
                })
                self.assertContains(response, 'Cette adresse e-mail existe déjà.')
                self.assertEqual(response.context['form'].errors['email'], ['Cette adresse e-mail existe déjà.'])
                self.assertNotContains(response, self.password)
                self.assertEqual(get_user_model().objects.filter(email=self.member.email).count(), 1)

    def test_failure_rolls_back_deletion_and_audit(self):
        from unittest.mock import patch
        from django.contrib.auth import get_user_model
        from apps.audit.models import ActivityLog
        from .services import delete_team_member

        original_logs = ActivityLog.objects.count()
        with patch('django.contrib.auth.models.User.delete', side_effect=RuntimeError('delete failed')):
            with self.assertRaises(RuntimeError):
                delete_team_member(actor=self.admin, user=self.member)
        self.assertTrue(get_user_model().objects.filter(pk=self.member.pk).exists())
        self.assertTrue(Profile.objects.filter(user_id=self.member.pk).exists())
        self.assertEqual(ActivityLog.objects.count(), original_logs)

    def test_push_subscriptions_are_removed_only_for_deleted_user(self):
        from apps.notifications.models import PushSubscription

        for user in (self.member, self.admin):
            PushSubscription.objects.create(
                user=user, endpoint=f'https://push.example.test/{user.pk}', p256dh='key', auth='auth',
            )
        self.login(self.admin)
        self.client.post(self.delete_url(), {'confirm': 'yes'})
        self.assertFalse(PushSubscription.objects.filter(user_id=self.member.pk).exists())
        self.assertTrue(PushSubscription.objects.filter(user_id=self.admin.pk).exists())

    def test_transactional_smoke_check_leaves_existing_accounts_untouched(self):
        import runpy
        from pathlib import Path
        from django.conf import settings
        from django.contrib.auth import get_user_model

        original_users = list(get_user_model().objects.order_by('pk').values_list('pk', flat=True))
        runpy.run_path(str(Path(settings.BASE_DIR) / 'tests' / 'smoke_team_deletion.py'))
        self.assertEqual(
            list(get_user_model().objects.order_by('pk').values_list('pk', flat=True)),
            original_users,
        )


class SettingsTests(TestCase):
    password = 'A-strong-test-password-482!'

    @classmethod
    def setUpTestData(cls):
        cls.admin = create_user_account(
            email='settings-admin@test.com', password=cls.password,
            full_name='Settings Admin', role=Profile.Role.ADMIN,
        )
        cls.manager = create_user_account(
            email='settings-manager@test.com', password=cls.password,
            full_name='Settings Manager', role=Profile.Role.MANAGER,
        )
        cls.member = create_user_account(
            email='settings-member@test.com', password=cls.password,
            full_name='Settings Member', role=Profile.Role.MEMBER,
        )

    def login(self, user):
        self.client.force_login(user, backend='apps.accounts.backends.EmailBackend')

    def test_every_role_can_update_own_profile_and_notification_preference(self):
        for user in (self.admin, self.manager, self.member):
            with self.subTest(role=user.profile.role):
                self.login(user)
                response = self.client.post(
                    reverse('accounts:settings'),
                    {
                        'action': 'profile', 'full_name': f'Updated {user.id}',
                        'email': user.profile.email, 'calendar_color': '#112233',
                        'avatar_url': '',
                    },
                )
                self.assertRedirects(response, reverse('accounts:settings'))
                user.profile.refresh_from_db()
                self.assertEqual(user.profile.calendar_color, '#112233')

                response = self.client.post(
                    reverse('accounts:settings'),
                    {'action': 'notifications'},
                )
                self.assertRedirects(response, reverse('accounts:settings'))
                user.profile.refresh_from_db()
                self.assertFalse(user.profile.in_app_notifications_enabled)

    def test_admin_updates_agency_and_manager_manages_types(self):
        from apps.calendar_app.models import AppointmentType
        from apps.core.models import AgencySettings

        self.login(self.admin)
        response = self.client.post(
            reverse('accounts:settings'),
            {
                'action': 'agency', 'agency_name': 'Digital Agency', 'logo_url': '',
                'timezone': 'Africa/Tunis', 'reminder_minutes': 45,
            },
        )
        self.assertRedirects(response, reverse('accounts:settings'))
        self.assertEqual(AgencySettings.load().reminder_minutes, 45)

        self.login(self.manager)
        response = self.client.post(
            reverse('accounts:settings'),
            {'action': 'type_create', 'name': 'Workshop'},
        )
        self.assertRedirects(response, reverse('accounts:settings'))
        appointment_type = AppointmentType.objects.get(name='Workshop')
        renamed = self.client.post(
            reverse('accounts:settings'),
            {'action': 'type_rename', 'type_id': appointment_type.id, 'name': 'Atelier'},
        )
        self.assertRedirects(renamed, reverse('accounts:settings'))
        appointment_type.refresh_from_db()
        self.assertEqual(appointment_type.name, 'Atelier')

        toggled = self.client.post(
            reverse('accounts:settings'),
            {'action': 'type_toggle', 'type_id': appointment_type.id},
        )
        self.assertRedirects(toggled, reverse('accounts:settings'))
        appointment_type.refresh_from_db()
        self.assertFalse(appointment_type.is_active)

    def test_member_cannot_change_agency_or_appointment_types(self):
        self.login(self.member)
        agency = self.client.post(
            reverse('accounts:settings'),
            {
                'action': 'agency', 'agency_name': 'Forbidden', 'logo_url': '',
                'timezone': 'Africa/Tunis', 'reminder_minutes': 30,
            },
        )
        appointment_type = self.client.post(
            reverse('accounts:settings'),
            {'action': 'type_create', 'name': 'Forbidden Type'},
        )
        self.assertEqual(agency.status_code, 403)
        self.assertEqual(appointment_type.status_code, 403)
