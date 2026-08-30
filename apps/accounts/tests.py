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
        admin = self.users[Profile.Role.ADMIN]
        member = self.users[Profile.Role.MEMBER]

        self.client.force_login(admin, backend='apps.accounts.backends.EmailBackend')
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'Nouveau rendez-vous')

        self.client.force_login(member, backend='apps.accounts.backends.EmailBackend')
        response = self.client.get(reverse('dashboard'))
        self.assertNotContains(response, 'Nouveau rendez-vous')

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

    def test_member_cannot_access_team(self):
        self.login(self.member)
        self.assertEqual(self.client.get(reverse('accounts:team')).status_code, 403)
        self.assertEqual(self.client.get(reverse('accounts:team-api')).status_code, 403)


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
