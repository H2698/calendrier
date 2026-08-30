import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Profile
from apps.accounts.services import create_user_account
from apps.audit.models import ActivityLog
from apps.calendar_app.models import Appointment, AppointmentType

from .models import Client
from .services import archive_client, create_client


class ClientModuleTests(TestCase):
    password = 'A-strong-test-password-482!'

    @classmethod
    def setUpTestData(cls):
        cls.admin = create_user_account(
            email='clients-admin@agency.test',
            password=cls.password,
            full_name='Clients Admin',
            role=Profile.Role.ADMIN,
        )
        cls.manager = create_user_account(
            email='clients-manager@agency.test',
            password=cls.password,
            full_name='Clients Manager',
            role=Profile.Role.MANAGER,
        )
        cls.member = create_user_account(
            email='clients-member@agency.test',
            password=cls.password,
            full_name='Clients Member',
            role=Profile.Role.MEMBER,
        )
        cls.client_record = create_client(
            actor=cls.admin,
            data={
                'name': 'Client Alpha',
                'company_name': 'Alpha Studio',
                'phone': '+216 20 000 000',
                'email': 'alpha@example.com',
                'notes': 'Client prioritaire',
            },
        )

    def _login(self, user):
        self.client.force_login(user, backend='apps.accounts.backends.EmailBackend')

    def test_admin_and_manager_can_view_clients_page(self):
        for user in (self.admin, self.manager):
            with self.subTest(role=user.profile.role):
                self._login(user)
                response = self.client.get(reverse('clients:list'))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'Client Alpha')
                self.client.logout()

    def test_member_cannot_access_global_clients(self):
        self._login(self.member)

        page_response = self.client.get(reverse('clients:list'))
        api_response = self.client.post(
            reverse('clients:api-list'),
            data=json.dumps({'name': 'Forbidden Client'}),
            content_type='application/json',
        )

        self.assertEqual(page_response.status_code, 403)
        self.assertEqual(api_response.status_code, 403)
        self.assertFalse(Client.objects.filter(name='Forbidden Client').exists())

    def test_admin_can_create_client_through_api(self):
        self._login(self.admin)

        response = self.client.post(
            reverse('clients:api-list'),
            data=json.dumps(
                {
                    'name': 'Nouveau Client',
                    'company_name': 'NC Agency',
                    'email': 'Contact@Example.com',
                }
            ),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        created = Client.active.get(name='Nouveau Client')
        self.assertEqual(created.email, 'contact@example.com')
        self.assertEqual(created.created_by, self.admin)
        self.assertTrue(ActivityLog.objects.filter(
            action='client_created', entity_id=created.id, user=self.admin
        ).exists())

    def test_manager_can_patch_client_through_api(self):
        self._login(self.manager)

        response = self.client.patch(
            reverse('clients:api-detail', args=(self.client_record.id,)),
            data=json.dumps({'phone': '+216 55 555 555'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.client_record.refresh_from_db()
        self.assertEqual(self.client_record.phone, '+216 55 555 555')
        self.assertTrue(ActivityLog.objects.filter(
            action='client_updated', entity_id=self.client_record.id,
            user=self.manager,
        ).exists())

    def test_search_and_pagination_metadata(self):
        self._login(self.admin)

        response = self.client.get(
            reverse('clients:api-list'),
            {'q': 'Alpha'},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['pagination']['count'], 1)
        self.assertEqual(payload['data'][0]['name'], 'Client Alpha')

    def test_archive_is_a_soft_delete(self):
        archive_client(client=self.client_record)

        self.assertTrue(Client.objects.filter(id=self.client_record.id).exists())
        self.assertFalse(Client.active.filter(id=self.client_record.id).exists())

    def test_api_archive_endpoint(self):
        self._login(self.admin)

        response = self.client.post(
            reverse('clients:api-archive', args=(self.client_record.id,))
        )

        self.assertEqual(response.status_code, 200)
        self.client_record.refresh_from_db()
        self.assertTrue(self.client_record.is_archived)
        self.assertTrue(ActivityLog.objects.filter(
            action='client_archived', entity_id=self.client_record.id,
            user=self.admin,
        ).exists())

    def test_invalid_json_returns_400(self):
        self._login(self.admin)

        response = self.client.post(
            reverse('clients:api-list'),
            data='{invalid',
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'validation_error')

    def test_list_and_detail_show_client_appointment_history(self):
        appointment_type = AppointmentType.objects.create(
            name='Client follow-up', created_by=self.admin
        )
        start_at = timezone.now() + timedelta(days=1)
        appointment = Appointment.objects.create(
            client=self.client_record, appointment_type=appointment_type,
            title='Suivi Alpha', start_at=start_at,
            end_at=start_at + timedelta(hours=1), created_by=self.admin,
            updated_by=self.admin,
        )
        appointment.members.add(self.manager)
        self._login(self.manager)

        client_list = self.client.get(reverse('clients:list'))
        detail = self.client.get(
            reverse('clients:detail', args=(self.client_record.id,))
        )

        self.assertEqual(client_list.status_code, 200)
        self.assertContains(client_list, start_at.strftime('%d/%m/%Y'))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, 'Suivi Alpha')
        self.assertContains(detail, 'Client follow-up')
