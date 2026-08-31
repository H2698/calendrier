"""Verify deletion against the configured DB; all test data is rolled back.

Run with: python manage.py shell -c "import runpy; runpy.run_path('tests/smoke_team_deletion.py')"
Never sends notifications or operates on existing users.
"""
from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import Client as Browser, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Profile
from apps.accounts.services import create_user_account
from apps.audit.models import ActivityLog
from apps.audit.services import log_activity
from apps.calendar_app.models import Appointment, AppointmentType
from apps.clients.models import Client
from apps.notifications.models import Notification, PushSubscription


def verify():
    token = uuid4().hex
    test_emails = [f'deletion-check-{role}-{token}@example.invalid' for role in ('admin', 'member')]
    with transaction.atomic(), override_settings(ALLOWED_HOSTS=['testserver']):
        admin = create_user_account(
            email=test_emails[0], password=uuid4().hex, full_name='Deletion Check Admin',
            role=Profile.Role.ADMIN,
        )
        target = create_user_account(
            email=test_emails[1], password=uuid4().hex, full_name='Deletion Check Member',
        )
        target_id = target.pk
        customer = Client.objects.create(name=f'Deletion check {token}', created_by=target)
        kind = AppointmentType.objects.create(name=f'Deletion check {token}', created_by=target)
        appointment = Appointment.objects.create(
            title='Deletion Check Appointment', appointment_type=kind, client=customer,
            created_by=target, updated_by=target, start_at=timezone.now(),
            end_at=timezone.now() + timedelta(hours=1),
        )
        appointment.members.add(admin, target)
        event = log_activity(
            actor=target, action='appointment_created', entity_type='appointment',
            entity_id=appointment.pk,
        )
        Notification.objects.create(user=target, title='Check', message='Check', type='appointment_created')
        PushSubscription.objects.create(
            user=target, endpoint=f'https://example.invalid/{token}', p256dh='check', auth='check',
        )
        admin_browser, old_session = Browser(), Browser()
        for browser, user in ((admin_browser, admin), (old_session, target)):
            browser.force_login(user, backend='apps.accounts.backends.EmailBackend')
        delete_url = reverse('accounts:team-member-delete', args=(target_id,))
        assert admin_browser.get(delete_url, secure=True).status_code == 200
        assert get_user_model().objects.filter(pk=target_id).exists()
        assert admin_browser.post(delete_url, {'confirm': 'yes'}, secure=True).status_code == 302
        assert not get_user_model().objects.filter(pk=target_id).exists()
        assert not Profile.objects.filter(user_id=target_id).exists()
        assert not Notification.objects.filter(user_id=target_id).exists()
        assert not PushSubscription.objects.filter(user_id=target_id).exists()
        appointment.refresh_from_db()
        customer.refresh_from_db()
        kind.refresh_from_db()
        event.refresh_from_db()
        assert appointment.created_by_id is None and appointment.updated_by_id is None
        assert customer.created_by_id is None and kind.created_by_id is None
        assert list(appointment.members.values_list('pk', flat=True)) == [admin.pk]
        assert event.user_id is None and event.actor_snapshot['id'] == str(target_id)
        deletion = ActivityLog.objects.get(action='user_permanently_deleted', entity_id=target_id)
        assert deletion.actor_snapshot['id'] == str(admin.pk)
        assert deletion.old_values['assigned_appointments'][0]['id'] == str(appointment.pk)
        assert old_session.get(reverse('dashboard'), secure=True).status_code == 302
        assert '_auth_user_id' not in old_session.session
        for route, kwargs in (
            ('accounts:team', {}), ('audit:history', {}),
            ('clients:detail', {'client_id': customer.pk}),
            ('clients:api-detail', {'client_id': customer.pk}),
            ('calendar_app:calendar-page', {}),
        ):
            assert admin_browser.get(reverse(route, kwargs=kwargs), secure=True).status_code == 200, route
        history = admin_browser.get(reverse('audit:activity-api'), {'user': str(target_id)}, secure=True)
        assert history.json()['data'][0]['user'] == 'Deletion Check Member'
        form = {
            'email': test_emails[1], 'password': uuid4().hex, 'full_name': 'Replacement Check',
            'role': 'member', 'calendar_color': '#2563EB',
        }
        assert admin_browser.post(reverse('accounts:team'), form, secure=True).status_code == 302
        replacement = get_user_model().objects.get(email=test_emails[1])
        assert replacement.pk != target_id and not replacement.appointments.exists()
        duplicate = admin_browser.post(reverse('accounts:team'), form, secure=True)
        assert duplicate.status_code == 200 and 'Cette adresse e-mail existe déjà.' in duplicate.content.decode()
        # Roll back every inserted/updated/deleted row, including sessions and audit.
        transaction.set_rollback(True)
    assert not get_user_model().objects.filter(email__in=test_emails).exists()
    assert not Client.objects.filter(name=f'Deletion check {token}').exists()
    print(f'Deletion smoke check passed ({connection.vendor}); all synthetic test data rolled back.')


verify()
