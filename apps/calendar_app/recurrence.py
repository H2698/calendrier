import calendar
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import log_activity

from .models import Appointment, AppointmentMember, RecurrenceSeries
from .services import AppointmentConflictError, appointment_snapshot, detect_conflicts


MAX_OCCURRENCES = 500


def _add_months(value, months):
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def occurrence_starts(*, start_at, frequency, interval_value, days_of_week, end_date):
    starts = []
    if end_date < start_at.date():
        raise ValidationError({'end_date': 'La fin de série précède le rendez-vous.'})
    cursor = start_at
    while len(starts) < MAX_OCCURRENCES:
        if frequency == RecurrenceSeries.Frequency.DAILY:
            cursor += timedelta(days=interval_value)
        elif frequency == RecurrenceSeries.Frequency.WEEKLY:
            cursor += timedelta(weeks=interval_value)
        elif frequency == RecurrenceSeries.Frequency.MONTHLY:
            cursor = _add_months(cursor, interval_value)
        else:
            cursor += timedelta(days=1)
            while cursor.date() <= end_date:
                weeks = (cursor.date() - start_at.date()).days // 7
                if cursor.weekday() in days_of_week and weeks % interval_value == 0:
                    break
                cursor += timedelta(days=1)
        if cursor.date() > end_date:
            return starts
        starts.append(cursor)
    raise ValidationError({'recurrence': f'La série dépasse {MAX_OCCURRENCES} occurrences.'})


@transaction.atomic
def expand_recurrence(*, actor, appointment, config, force_conflicts=False):
    series = RecurrenceSeries(
        frequency=config.get('frequency'),
        interval_value=int(config.get('interval_value', 1)),
        days_of_week=config.get('days_of_week', []),
        end_date=config.get('end_date'),
    )
    series.full_clean()
    members = list(appointment.members.select_related('profile'))
    duration = appointment.end_at - appointment.start_at
    starts = occurrence_starts(
        start_at=appointment.start_at,
        frequency=series.frequency,
        interval_value=series.interval_value,
        days_of_week=series.days_of_week,
        end_date=series.end_date,
    )
    all_conflicts = []
    for start_at in starts:
        all_conflicts.extend(
            detect_conflicts(
                members=members,
                start_at=start_at,
                end_at=start_at + duration,
            )
        )
    if all_conflicts and not force_conflicts:
        raise AppointmentConflictError(all_conflicts)

    series.save()
    appointment.recurrence_series = series
    appointment.save(update_fields=('recurrence_series', 'updated_at'))
    created = [appointment]
    for start_at in starts:
        occurrence = Appointment.objects.create(
            client=appointment.client,
            appointment_type=appointment.appointment_type,
            title=appointment.title,
            description=appointment.description,
            start_at=start_at,
            end_at=start_at + duration,
            status=appointment.status,
            notes=appointment.notes,
            recurrence_series=series,
            created_by=actor,
            updated_by=actor,
        )
        AppointmentMember.objects.bulk_create(
            [AppointmentMember(appointment=occurrence, user=member) for member in members]
        )
        log_activity(
            actor=actor,
            action='appointment_created',
            entity_type='appointment',
            entity_id=occurrence.id,
            new_values=appointment_snapshot(occurrence),
        )
        created.append(occurrence)
    return created, all_conflicts
