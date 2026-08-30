from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Profile
from apps.audit.services import log_activity
from apps.notifications.models import Notification
from apps.notifications.services import schedule_appointment_notifications

from .models import Appointment, AppointmentMember


EDITABLE_FIELDS = (
    'client',
    'appointment_type',
    'title',
    'description',
    'start_at',
    'end_at',
    'status',
    'notes',
)


class AppointmentConflictError(Exception):
    def __init__(self, conflicts):
        self.conflicts = conflicts
        super().__init__('Un ou plusieurs membres ont déjà un rendez-vous.')


def ensure_calendar_manager(actor):
    profile = getattr(actor, 'profile', None)
    if not actor.is_authenticated or not profile or not profile.can_manage_calendar:
        raise PermissionDenied


def _active_members(member_ids):
    ids = {str(member_id) for member_id in member_ids}
    users = list(
        get_user_model().objects.select_related('profile').filter(
            id__in=ids,
            is_active=True,
            profile__is_active=True,
        )
    )
    if len(users) != len(ids):
        raise ValidationError({'members': 'Un ou plusieurs membres sont invalides ou inactifs.'})
    return users


def detect_conflicts(*, members, start_at, end_at, exclude_appointment=None):
    queryset = AppointmentMember.objects.select_related(
        'user__profile', 'appointment'
    ).filter(
        user__in=members,
        appointment__deleted_at__isnull=True,
        appointment__start_at__lt=end_at,
        appointment__end_at__gt=start_at,
    ).exclude(appointment__status=Appointment.Status.CANCELLED)
    if exclude_appointment:
        queryset = queryset.exclude(appointment=exclude_appointment)
    return [
        {
            'user_id': link.user_id,
            'user_name': link.user.profile.full_name,
            'appointment_id': link.appointment_id,
            'title': link.appointment.title,
            'start_at': link.appointment.start_at,
            'end_at': link.appointment.end_at,
        }
        for link in queryset
    ]


def appointment_snapshot(appointment):
    return {
        'id': appointment.id,
        'client_id': appointment.client_id,
        'appointment_type_id': appointment.appointment_type_id,
        'title': appointment.title,
        'description': appointment.description,
        'start_at': appointment.start_at,
        'end_at': appointment.end_at,
        'status': appointment.status,
        'notes': appointment.notes,
        'member_ids': list(appointment.members.values_list('id', flat=True)),
    }


@transaction.atomic
def create_appointment(*, actor, data, member_ids, force_conflicts=False):
    ensure_calendar_manager(actor)
    members = _active_members(member_ids)
    values = {field: data[field] for field in EDITABLE_FIELDS if field in data}
    appointment = Appointment(created_by=actor, updated_by=actor, **values)
    appointment.full_clean()
    conflicts = detect_conflicts(
        members=members,
        start_at=appointment.start_at,
        end_at=appointment.end_at,
    )
    if conflicts and not force_conflicts:
        raise AppointmentConflictError(conflicts)

    appointment.save()
    AppointmentMember.objects.bulk_create(
        [AppointmentMember(appointment=appointment, user=member) for member in members]
    )
    log_activity(
        actor=actor,
        action='appointment_created',
        entity_type='appointment',
        entity_id=appointment.id,
        new_values=appointment_snapshot(appointment),
    )
    schedule_appointment_notifications(appointment, Notification.Type.CREATED)
    schedule_appointment_notifications(appointment, Notification.Type.REMINDER)
    return appointment, conflicts


@transaction.atomic
def update_appointment(
    *,
    actor,
    appointment,
    data,
    member_ids=None,
    force_conflicts=False,
    audit_action='appointment_updated',
):
    ensure_calendar_manager(actor)
    old_values = appointment_snapshot(appointment)
    for field in EDITABLE_FIELDS:
        if field in data:
            setattr(appointment, field, data[field])
    appointment.updated_by = actor
    appointment.full_clean()
    members = (
        _active_members(member_ids)
        if member_ids is not None
        else list(appointment.members.select_related('profile'))
    )
    conflicts = detect_conflicts(
        members=members,
        start_at=appointment.start_at,
        end_at=appointment.end_at,
        exclude_appointment=appointment,
    )
    if conflicts and not force_conflicts:
        raise AppointmentConflictError(conflicts)

    appointment.save()
    if member_ids is not None:
        AppointmentMember.objects.filter(appointment=appointment).delete()
        AppointmentMember.objects.bulk_create(
            [AppointmentMember(appointment=appointment, user=member) for member in members]
        )
    new_values = appointment_snapshot(appointment)
    log_activity(
        actor=actor,
        action=audit_action,
        entity_type='appointment',
        entity_id=appointment.id,
        old_values=old_values,
        new_values=new_values,
    )
    old_member_ids = {str(member_id) for member_id in old_values['member_ids']}
    new_member_ids = {str(member_id) for member_id in new_values['member_ids']}
    for member_id in sorted(new_member_ids - old_member_ids):
        log_activity(
            actor=actor, action='appointment_member_assigned',
            entity_type='appointment', entity_id=appointment.id,
            new_values={'member_id': member_id},
        )
    for member_id in sorted(old_member_ids - new_member_ids):
        log_activity(
            actor=actor, action='appointment_member_unassigned',
            entity_type='appointment', entity_id=appointment.id,
            old_values={'member_id': member_id},
        )
    schedule_appointment_notifications(appointment, Notification.Type.UPDATED)
    schedule_appointment_notifications(appointment, Notification.Type.REMINDER)
    return appointment, conflicts


@transaction.atomic
def move_appointment(*, actor, appointment, start_at, end_at, force_conflicts=False):
    appointment, conflicts = update_appointment(
        actor=actor,
        appointment=appointment,
        data={'start_at': start_at, 'end_at': end_at},
        force_conflicts=force_conflicts,
        audit_action='appointment_moved',
    )
    return appointment, conflicts


@transaction.atomic
def cancel_appointment(*, actor, appointment):
    ensure_calendar_manager(actor)
    old_values = appointment_snapshot(appointment)
    appointment.status = Appointment.Status.CANCELLED
    appointment.cancelled_at = timezone.now()
    appointment.updated_by = actor
    appointment.save(update_fields=('status', 'cancelled_at', 'updated_by', 'updated_at'))
    log_activity(
        actor=actor,
        action='appointment_cancelled',
        entity_type='appointment',
        entity_id=appointment.id,
        old_values=old_values,
        new_values=appointment_snapshot(appointment),
    )
    Notification.objects.filter(
        appointment=appointment,
        type=Notification.Type.REMINDER,
        sent_at__isnull=True,
    ).delete()
    schedule_appointment_notifications(appointment, Notification.Type.CANCELLED)
    return appointment
