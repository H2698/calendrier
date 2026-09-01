"""Reversible smoke check for immutable appointment reports on the configured DB."""

from datetime import timedelta
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Profile
from apps.accounts.services import create_user_account
from apps.audit.models import ActivityLog
from apps.calendar_app.models import Appointment, AppointmentMember, AppointmentReport, AppointmentType
from apps.calendar_app.services import submit_appointment_report
from apps.notifications.models import Notification
from apps.notifications.services import schedule_report_notifications


marker = uuid4().hex
with transaction.atomic():
    admin = create_user_account(
        email=f'report-admin-{marker}@smoke.invalid', password=uuid4().hex,
        full_name='Report Smoke Admin', role=Profile.Role.ADMIN,
    )
    member = create_user_account(
        email=f'report-member-{marker}@smoke.invalid', password=uuid4().hex,
        full_name='Report Smoke Member', role=Profile.Role.MEMBER,
    )
    appointment_type = AppointmentType.objects.create(
        name=f'Report smoke {marker}', created_by=admin,
    )
    end_at = timezone.now() - timedelta(minutes=5)
    appointment = Appointment.objects.create(
        appointment_type=appointment_type, title=f'Report smoke {marker}',
        start_at=end_at - timedelta(hours=1), end_at=end_at,
        status=Appointment.Status.COMPLETED,
        created_by=admin, updated_by=admin,
    )
    AppointmentMember.objects.create(appointment=appointment, user=member)

    assert schedule_report_notifications(appointment) == 1
    report = submit_appointment_report(
        actor=member, appointment=appointment,
        content='Compte rendu synthétique de contrôle PostgreSQL.',
    )
    assert AppointmentReport.objects.filter(pk=report.pk).exists()
    report_notification = Notification.objects.get(
        appointment=appointment, user=member,
        type=Notification.Type.REPORT_REQUIRED,
    )
    assert report_notification.is_read
    assert report_notification.sent_at is not None
    assert ActivityLog.objects.filter(
        action='appointment_report_submitted', entity_id=report.pk,
        new_values__immutable=True,
    ).exists()

    report.content = 'Modification interdite.'
    try:
        report.save()
    except ValidationError:
        pass
    else:
        raise AssertionError('An already submitted report was modified.')

    transaction.set_rollback(True)

print('Appointment report smoke check passed; all synthetic data rolled back.')
