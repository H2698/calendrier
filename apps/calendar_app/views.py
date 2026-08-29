import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET, require_http_methods

from apps.accounts.models import Profile
from apps.accounts.permissions import calendar_manager_required
from apps.clients.models import Client

from .models import Appointment, AppointmentMember, AppointmentType
from .services import (
    AppointmentConflictError,
    cancel_appointment,
    create_appointment,
    ensure_calendar_manager,
    move_appointment,
    update_appointment,
)


def _json_body(request):
    try:
        data = json.loads(request.body or b'{}')
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValidationError('Corps JSON invalide.') from exc
    if not isinstance(data, dict):
        raise ValidationError('Le corps JSON doit être un objet.')
    return data


def _datetime(value, field):
    parsed = parse_datetime(value) if isinstance(value, str) else value
    if parsed is None:
        raise ValidationError({field: 'Date/heure ISO 8601 invalide.'})
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
    return parsed


def _validation_error(exc):
    details = exc.message_dict if hasattr(exc, 'message_dict') else exc.messages
    return JsonResponse({'error': 'validation_error', 'details': details}, status=400)


def _conflict_error(exc):
    return JsonResponse(
        {
            'error': 'appointment_conflict',
            'message': 'Un ou plusieurs membres ont déjà un rendez-vous.',
            'conflicts': [
                {
                    **conflict,
                    'user_id': str(conflict['user_id']),
                    'appointment_id': str(conflict['appointment_id']),
                    'start_at': conflict['start_at'].isoformat(),
                    'end_at': conflict['end_at'].isoformat(),
                }
                for conflict in exc.conflicts
            ],
        },
        status=409,
    )


def _resolved_data(data, *, partial=False):
    values = {}
    scalar_fields = ('title', 'description', 'status', 'notes')
    for field in scalar_fields:
        if field in data:
            values[field] = data[field]
    for field in ('start_at', 'end_at'):
        if field in data:
            values[field] = _datetime(data[field], field)
    if 'appointment_type_id' in data:
        values['appointment_type'] = get_object_or_404(
            AppointmentType,
            id=data['appointment_type_id'],
            is_active=True,
        )
    elif not partial:
        raise ValidationError({'appointment_type_id': 'Ce champ est obligatoire.'})
    if 'client_id' in data:
        values['client'] = (
            get_object_or_404(Client.active, id=data['client_id'])
            if data['client_id']
            else None
        )
    return values


def _member_payload(user):
    return {
        'id': user.id,
        'name': user.profile.full_name,
        'color': user.profile.calendar_color,
    }


def _appointment_payload(appointment, viewer):
    members = list(appointment.members.all())
    assigned = any(member.id == viewer.id for member in members)
    role = viewer.profile.role
    full_access = role in {Profile.Role.ADMIN, Profile.Role.MANAGER} or assigned
    payload = {
        'id': str(appointment.id),
        'title': appointment.title if full_access else 'Rendez-vous agence',
        'appointment_type': {
            'id': str(appointment.appointment_type_id),
            'name': appointment.appointment_type.name,
        },
        'start_at': appointment.start_at.isoformat(),
        'end_at': appointment.end_at.isoformat(),
        'status': appointment.status,
        'members': [_member_payload(member) for member in members],
        'is_assigned': assigned,
    }
    if full_access:
        payload.update(
            {
                'description': appointment.description,
                'notes': appointment.notes,
                'client': (
                    {
                        'id': str(appointment.client_id),
                        'name': appointment.client.name,
                        'company_name': appointment.client.company_name,
                        'phone': appointment.client.phone,
                        'email': appointment.client.email,
                    }
                    if appointment.client
                    else None
                ),
            }
        )
    return payload


def _appointment_queryset():
    return Appointment.objects.filter(deleted_at__isnull=True).select_related(
        'appointment_type', 'client', 'created_by', 'updated_by'
    ).prefetch_related(
        Prefetch(
            'members',
            queryset=get_user_model().objects.select_related('profile').order_by('profile__full_name'),
        )
    )


@require_GET
def appointment_types_api(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'authentication_required'}, status=401)
    types = AppointmentType.objects.filter(is_active=True)
    return JsonResponse(
        {'data': [{'id': str(item.id), 'name': item.name} for item in types]}
    )


@require_GET
def calendar_api(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'authentication_required'}, status=401)
    try:
        start_at = _datetime(request.GET.get('start'), 'start')
        end_at = _datetime(request.GET.get('end'), 'end')
    except ValidationError as exc:
        return _validation_error(exc)
    queryset = _appointment_queryset().filter(start_at__lt=end_at, end_at__gt=start_at)
    if member := request.GET.get('member'):
        queryset = queryset.filter(members__id=member)
    if appointment_type := request.GET.get('type'):
        queryset = queryset.filter(appointment_type_id=appointment_type)
    if status := request.GET.get('status'):
        queryset = queryset.filter(status=status)
    return JsonResponse(
        {'data': [_appointment_payload(item, request.user) for item in queryset.distinct()]}
    )


@require_http_methods(['POST'])
@calendar_manager_required
def appointments_api(request):
    try:
        data = _json_body(request)
        values = _resolved_data(data)
        appointment, conflicts = create_appointment(
            actor=request.user,
            data=values,
            member_ids=data.get('member_ids', []),
            force_conflicts=bool(data.get('force_conflicts', False)),
        )
    except AppointmentConflictError as exc:
        return _conflict_error(exc)
    except ValidationError as exc:
        return _validation_error(exc)
    appointment = _appointment_queryset().get(id=appointment.id)
    return JsonResponse(
        {'data': _appointment_payload(appointment, request.user), 'conflicts': len(conflicts)},
        status=201,
    )


@require_http_methods(['GET', 'PATCH'])
def appointment_detail_api(request, appointment_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'authentication_required'}, status=401)
    appointment = get_object_or_404(_appointment_queryset(), id=appointment_id)
    if request.method == 'PATCH':
        try:
            ensure_calendar_manager(request.user)
            data = _json_body(request)
            appointment, conflicts = update_appointment(
                actor=request.user,
                appointment=appointment,
                data=_resolved_data(data, partial=True),
                member_ids=data.get('member_ids') if 'member_ids' in data else None,
                force_conflicts=bool(data.get('force_conflicts', False)),
            )
        except AppointmentConflictError as exc:
            return _conflict_error(exc)
        except ValidationError as exc:
            return _validation_error(exc)
        appointment = _appointment_queryset().get(id=appointment.id)
    return JsonResponse({'data': _appointment_payload(appointment, request.user)})


@require_http_methods(['POST'])
@calendar_manager_required
def appointment_move_api(request, appointment_id):
    appointment = get_object_or_404(_appointment_queryset(), id=appointment_id)
    try:
        data = _json_body(request)
        appointment, conflicts = move_appointment(
            actor=request.user,
            appointment=appointment,
            start_at=_datetime(data.get('start_at'), 'start_at'),
            end_at=_datetime(data.get('end_at'), 'end_at'),
            force_conflicts=bool(data.get('force_conflicts', False)),
        )
    except AppointmentConflictError as exc:
        return _conflict_error(exc)
    except ValidationError as exc:
        return _validation_error(exc)
    appointment = _appointment_queryset().get(id=appointment.id)
    return JsonResponse({'data': _appointment_payload(appointment, request.user)})


@require_http_methods(['POST'])
@calendar_manager_required
def appointment_cancel_api(request, appointment_id):
    appointment = get_object_or_404(_appointment_queryset(), id=appointment_id)
    cancel_appointment(actor=request.user, appointment=appointment)
    appointment = _appointment_queryset().get(id=appointment.id)
    return JsonResponse({'data': _appointment_payload(appointment, request.user)})
