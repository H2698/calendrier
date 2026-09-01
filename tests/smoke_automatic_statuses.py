"""Verify automatic appointment status rules; roll back every synthetic row."""
from datetime import timedelta
from uuid import uuid4

from django.db import connection, transaction
from django.utils import timezone

from apps.accounts.models import Profile
from apps.accounts.services import create_user_account
from apps.audit.models import ActivityLog
from apps.calendar_app.models import Appointment, AppointmentType
from apps.calendar_app.services import refresh_appointment_statuses


def verify():
    token = uuid4().hex
    email = f'automatic-status-check-{token}@example.invalid'
    reference = timezone.now()
    ids = []
    with transaction.atomic():
        admin = create_user_account(
            email=email, password=uuid4().hex,
            full_name='Automatic Status Check', role=Profile.Role.ADMIN,
        )
        kind = AppointmentType.objects.create(name=f'Automatic status {token}', created_by=admin)

        def create(status, start_delta, end_delta, *, deleted=False):
            appointment = Appointment.objects.create(
                title=f'Automatic status {status} {uuid4().hex}', status=status,
                appointment_type=kind, start_at=reference + start_delta,
                end_at=reference + end_delta, created_by=admin, updated_by=admin,
                deleted_at=reference if deleted else None,
            )
            ids.append(appointment.pk)
            return appointment

        at_start = create('planned', timedelta(), timedelta(hours=1))
        planned_finished = create('planned', -timedelta(hours=2), -timedelta(hours=1))
        confirmed_finished = create('confirmed', -timedelta(hours=2), timedelta())
        protected = [
            create(status, -timedelta(hours=2), -timedelta(hours=1))
            for status in ('cancelled', 'postponed', 'completed')
        ]
        deleted = create('planned', -timedelta(hours=2), -timedelta(hours=1), deleted=True)
        result = refresh_appointment_statuses(now=reference)
        assert result['confirmed'] >= 1 and result['completed'] >= 2
        for appointment, expected in (
            (at_start, 'confirmed'), (planned_finished, 'completed'),
            (confirmed_finished, 'completed'), (deleted, 'planned'),
            *[(item, item.status) for item in protected],
        ):
            appointment.refresh_from_db()
            assert appointment.status == expected
        logs = ActivityLog.objects.filter(
            entity_id__in=ids, action='appointment_status_changed',
            new_values__automatic=True,
        )
        assert logs.count() == 3 and all(log.user_id is None for log in logs)
        transaction.set_rollback(True)
    assert not Appointment.objects.filter(pk__in=ids).exists()
    assert not Profile.objects.filter(email=email).exists()
    print(f'Automatic status smoke check passed ({connection.vendor}); all synthetic data rolled back.')


verify()
