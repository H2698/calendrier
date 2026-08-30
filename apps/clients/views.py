import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import OuterRef, Q, Subquery
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from apps.accounts.permissions import calendar_manager_required
from apps.calendar_app.models import Appointment

from .forms import ClientForm
from .models import Client
from .services import archive_client, create_client, update_client


def _client_payload(client):
    return {
        'id': str(client.id),
        'name': client.name,
        'company_name': client.company_name,
        'phone': client.phone,
        'email': client.email,
        'notes': client.notes,
        'created_by': client.created_by.profile.full_name,
        'created_at': client.created_at.isoformat(),
        'updated_at': client.updated_at.isoformat(),
    }


def _json_body(request):
    try:
        data = json.loads(request.body or b'{}')
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValidationError('Corps JSON invalide.') from exc
    if not isinstance(data, dict):
        raise ValidationError('Le corps JSON doit être un objet.')
    return data


def _validation_error(exc):
    if hasattr(exc, 'message_dict'):
        details = exc.message_dict
    else:
        details = exc.messages
    return JsonResponse({'error': 'validation_error', 'details': details}, status=400)


@login_required
@calendar_manager_required
def client_list_page(request):
    search = request.GET.get('q', '').strip()
    now = timezone.now()
    active_appointments = Appointment.objects.filter(
        client=OuterRef('pk'), deleted_at__isnull=True,
    ).exclude(status=Appointment.Status.CANCELLED)
    queryset = Client.active.select_related(
        'created_by', 'created_by__profile'
    ).annotate(
        next_appointment_at=Subquery(
            active_appointments.filter(start_at__gte=now)
            .order_by('start_at').values('start_at')[:1]
        ),
        last_appointment_at=Subquery(
            active_appointments.filter(start_at__lt=now)
            .order_by('-start_at').values('start_at')[:1]
        ),
    )
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search)
            | Q(company_name__icontains=search)
            | Q(phone__icontains=search)
            | Q(email__icontains=search)
        )
    page = Paginator(queryset, 20).get_page(request.GET.get('page'))
    return render(
        request,
        'clients/list.html',
        {'page': page, 'search': search},
    )


@login_required
@calendar_manager_required
def client_detail_page(request, client_id):
    client = get_object_or_404(Client.active, id=client_id)
    appointments = client.appointments.filter(
        deleted_at__isnull=True,
    ).select_related('appointment_type').prefetch_related(
        'members__profile'
    ).order_by('-start_at')
    appointment_page = Paginator(appointments, 20).get_page(request.GET.get('page'))
    next_appointment = appointments.exclude(
        status=Appointment.Status.CANCELLED
    ).filter(start_at__gte=timezone.now()).order_by('start_at').first()
    return render(
        request, 'clients/detail.html',
        {
            'client': client,
            'appointment_page': appointment_page,
            'next_appointment': next_appointment,
        },
    )


@login_required
@calendar_manager_required
def client_create_page(request):
    form = ClientForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        client = create_client(actor=request.user, data=form.cleaned_data)
        return redirect('clients:detail', client_id=client.id)
    return render(request, 'clients/form.html', {'form': form, 'mode': 'create'})


@login_required
@calendar_manager_required
def client_edit_page(request, client_id):
    client = get_object_or_404(Client.active, id=client_id)
    form = ClientForm(request.POST or None, instance=client)
    if request.method == 'POST' and form.is_valid():
        update_client(client=client, data=form.cleaned_data, actor=request.user)
        return redirect('clients:detail', client_id=client.id)
    return render(
        request,
        'clients/form.html',
        {'form': form, 'mode': 'edit', 'client': client},
    )


@require_http_methods(['GET', 'POST'])
@calendar_manager_required
def clients_api(request):
    if request.method == 'POST':
        try:
            client = create_client(actor=request.user, data=_json_body(request))
        except ValidationError as exc:
            return _validation_error(exc)
        return JsonResponse({'data': _client_payload(client)}, status=201)

    search = request.GET.get('q', '').strip()
    queryset = Client.active.select_related('created_by', 'created_by__profile')
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search) | Q(company_name__icontains=search)
        )
    paginator = Paginator(queryset, 20)
    page = paginator.get_page(request.GET.get('page'))
    return JsonResponse(
        {
            'data': [_client_payload(client) for client in page.object_list],
            'pagination': {
                'page': page.number,
                'pages': paginator.num_pages,
                'count': paginator.count,
                'has_next': page.has_next(),
                'has_previous': page.has_previous(),
            },
        }
    )


@require_http_methods(['GET', 'PATCH'])
@calendar_manager_required
def client_detail_api(request, client_id):
    client = get_object_or_404(
        Client.active.select_related('created_by', 'created_by__profile'),
        id=client_id,
    )
    if request.method == 'PATCH':
        try:
            update_client(client=client, data=_json_body(request), actor=request.user)
        except ValidationError as exc:
            return _validation_error(exc)
    return JsonResponse({'data': _client_payload(client)})


@require_http_methods(['POST'])
@calendar_manager_required
def client_archive_api(request, client_id):
    client = get_object_or_404(Client.active, id=client_id)
    archive_client(client=client, actor=request.user)
    return JsonResponse({'data': {'id': str(client.id), 'archived': True}})
