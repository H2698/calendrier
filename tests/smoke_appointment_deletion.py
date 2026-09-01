"""Verify appointment deletion on the configured DB; roll back all test data."""
from datetime import timedelta
from uuid import uuid4

from django.db import connection, transaction
from django.test import Client as Browser, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Profile
from apps.accounts.services import create_user_account
from apps.audit.models import ActivityLog
from apps.calendar_app.models import Appointment, AppointmentType
from apps.clients.models import Client
from apps.notifications.models import Notification


def verify():
    token = uuid4().hex
    admin_email = f'appointment-delete-admin-{token}@example.invalid'
    with transaction.atomic(), override_settings(ALLOWED_HOSTS=['testserver']):
        admin = create_user_account(
            email=admin_email, password=uuid4().hex,
            full_name='Appointment Delete Check Admin', role=Profile.Role.ADMIN,
        )
        member = create_user_account(
            email=f'appointment-delete-member-{token}@example.invalid', password=uuid4().hex,
            full_name='Appointment Delete Check Member',
        )
        kind = AppointmentType.objects.create(name=f'Delete check {token}', created_by=admin)
        customer = Client.objects.create(name=f'Delete check {token}', created_by=admin)
        appointment = Appointment.objects.create(
            title='Appointment Delete Check', appointment_type=kind, client=customer,
            start_at=timezone.now(), end_at=timezone.now() + timedelta(hours=1),
            created_by=admin, updated_by=admin,
        )
        appointment.members.add(member)
        sent = Notification.objects.create(
            user=member, appointment=appointment, type=Notification.Type.CREATED,
            title='Already sent', message='Already sent', sent_at=timezone.now(),
        )
        pending = Notification.objects.create(
            user=member, appointment=appointment, type=Notification.Type.REMINDER,
            title='Pending', message='Pending', scheduled_for=timezone.now(),
        )
        member_browser = Browser()
        member_browser.force_login(member, backend='apps.accounts.backends.EmailBackend')
        delete_url = reverse('calendar_app:appointment-delete-api', args=(appointment.pk,))
        assert member_browser.post(delete_url, secure=True).status_code == 403
        admin_browser = Browser()
        admin_browser.force_login(admin, backend='apps.accounts.backends.EmailBackend')
        response = admin_browser.post(delete_url, secure=True)
        assert response.status_code == 200 and response.json()['data']['deleted'] is True
        appointment.refresh_from_db()
        assert appointment.deleted_at and appointment.members.filter(pk=member.pk).exists()
        assert Notification.objects.filter(pk=sent.pk).exists()
        assert not Notification.objects.filter(pk=pending.pk).exists()
        audit = ActivityLog.objects.get(
            action='appointment_deleted', entity_id=appointment.pk,
        )
        assert audit.user_id == admin.pk and audit.old_values['title'] == appointment.title
        assert admin_browser.get(
            reverse('calendar_app:appointment-detail-api', args=(appointment.pk,)), secure=True,
        ).status_code == 404
        assert 'Rendez-vous supprimé' in admin_browser.get(
            reverse('audit:history'), secure=True,
        ).content.decode()
        transaction.set_rollback(True)
    assert not Appointment.objects.filter(title='Appointment Delete Check').exists()
    assert not Profile.objects.filter(email=admin_email).exists()
    print(f'Appointment deletion smoke check passed ({connection.vendor}); all synthetic data rolled back.')


verify()
