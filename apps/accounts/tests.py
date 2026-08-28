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
