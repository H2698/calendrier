from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Profile
from apps.accounts.services import create_user_account

from .models import ActivityLog


class HistoryPageTests(TestCase):
    password = 'A-strong-test-password-482!'

    @classmethod
    def setUpTestData(cls):
        cls.admin = create_user_account(
            email='history-admin@agency.test', password=cls.password,
            full_name='History Admin', role=Profile.Role.ADMIN,
        )
        cls.manager = create_user_account(
            email='history-manager@agency.test', password=cls.password,
            full_name='History Manager', role=Profile.Role.MANAGER,
        )
        cls.member = create_user_account(
            email='history-member@agency.test', password=cls.password,
            full_name='History Member', role=Profile.Role.MEMBER,
        )
        ActivityLog.objects.create(
            user=cls.admin, action='appointment_created', entity_type='appointment',
            entity_id='appointment-one', new_values={'title': 'Visible audit record'},
        )
        ActivityLog.objects.create(
            user=cls.manager, action='client_updated', entity_type='client',
            entity_id='client-one', old_values={'name': 'Old'}, new_values={'name': 'New'},
        )

    def _login(self, user):
        self.client.force_login(user, backend='apps.accounts.backends.EmailBackend')

    def test_admin_and_manager_can_open_history_but_member_gets_403(self):
        for user in (self.admin, self.manager):
            self._login(user)
            response = self.client.get(reverse('audit:history'))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Historique des modifications')

        self._login(self.member)
        self.assertEqual(self.client.get(reverse('audit:history')).status_code, 403)
        self.assertEqual(self.client.get(reverse('audit:activity-api')).status_code, 403)

    def test_history_filters_apply_to_page_and_api(self):
        self._login(self.admin)
        filters = {'action': 'client_updated', 'entity_type': 'client', 'user': self.manager.id}

        page = self.client.get(reverse('audit:history'), filters)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'client-one')
        self.assertNotContains(page, 'appointment-one')

        api = self.client.get(reverse('audit:activity-api'), filters)
        self.assertEqual(api.status_code, 200)
        self.assertEqual(api.json()['pagination']['count'], 1)
        self.assertEqual(api.json()['data'][0]['entity_id'], 'client-one')
