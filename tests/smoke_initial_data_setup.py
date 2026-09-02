"""Reversible smoke check for the initial data setup page."""

from uuid import uuid4

from django.contrib.messages.storage.fallback import FallbackStorage
from django.db import connection, transaction
from django.test import RequestFactory

from apps.accounts.models import Profile
from apps.accounts.services import create_user_account
from apps.accounts.views import initial_data_setup_page
from apps.audit.models import ActivityLog
from apps.calendar_app.models import AppointmentType
from apps.core.models import AgencySettings


marker = uuid4().hex
email = f'data-setup-{marker}@smoke.invalid'
type_name = f'Data setup {marker}'
original_settings = AgencySettings.objects.filter(pk=1).values().first()

with transaction.atomic():
    admin = create_user_account(
        email=email, password=uuid4().hex,
        full_name='Data Setup Smoke Admin', role=Profile.Role.ADMIN,
    )
    request = RequestFactory().post('/settings/data-setup/', {
        'agency_name': 'Data Setup Smoke Agency',
        'logo_url': '',
        'timezone': 'Africa/Tunis',
        'reminder_minutes': 25,
        'appointment_types': type_name,
    })
    request.user = admin
    request.session = {}
    request._messages = FallbackStorage(request)

    response = initial_data_setup_page(request)

    assert response.status_code == 302
    settings_record = AgencySettings.load()
    assert settings_record.agency_name == 'Data Setup Smoke Agency'
    assert settings_record.setup_completed_at is not None
    assert AppointmentType.objects.filter(name=type_name, is_active=True).exists()
    assert ActivityLog.objects.filter(
        action='initial_data_setup_saved', user=admin,
    ).exists()
    transaction.set_rollback(True)

assert not Profile.objects.filter(email=email).exists()
assert not AppointmentType.objects.filter(name=type_name).exists()
assert AgencySettings.objects.filter(pk=1).values().first() == original_settings
print(f'Initial data setup smoke check passed ({connection.vendor}); all synthetic changes rolled back.')
