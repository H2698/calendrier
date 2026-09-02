from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET

from apps.accounts.permissions import calendar_manager_required

from .models import ActivityLog


ACTION_LABELS = {
    'appointment_created': 'Rendez-vous créé',
    'appointment_updated': 'Rendez-vous modifié',
    'appointment_moved': 'Rendez-vous déplacé',
    'appointment_cancelled': 'Rendez-vous annulé',
    'appointment_deleted': 'Rendez-vous supprimé',
    'appointment_report_submitted': 'Rapport de rendez-vous envoyé',
    'initial_data_setup_saved': 'Configuration initiale enregistrée',
    'appointment_member_assigned': 'Membre affecté',
    'appointment_member_unassigned': 'Membre désaffecté',
    'appointment_status_changed': 'Statut du rendez-vous modifié',
    'client_created': 'Client créé',
    'client_updated': 'Client modifié',
    'client_archived': 'Client archivé',
    'user_created': 'Utilisateur créé',
    'user_updated': 'Utilisateur modifié',
    'user_role_changed': 'Rôle utilisateur modifié',
    'user_disabled': 'Utilisateur désactivé',
    'user_deleted': 'Membre supprimé de l’équipe',
    'user_permanently_deleted': 'Membre supprimé définitivement',
    'user_enabled': 'Utilisateur activé',
}


def _filtered_activity(request):
    queryset = ActivityLog.objects.select_related('user', 'user__profile')
    if action := request.GET.get('action'):
        queryset = queryset.filter(action=action)
    if entity_type := request.GET.get('entity_type'):
        queryset = queryset.filter(entity_type=entity_type)
    if user_id := request.GET.get('user'):
        if user_id.isdecimal():
            queryset = queryset.filter(Q(user_id=user_id) | Q(actor_snapshot__id=user_id))
        else:
            queryset = queryset.none()
    if date_from := parse_date(request.GET.get('date_from', '')):
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to := parse_date(request.GET.get('date_to', '')):
        queryset = queryset.filter(created_at__date__lte=date_to)
    return queryset


def _history_users():
    users = {
        str(user.pk): {'id': str(user.pk), 'name': user.profile.full_name}
        for user in get_user_model().objects.select_related('profile')
    }
    snapshots = ActivityLog.objects.exclude(actor_snapshot={}).order_by().values_list(
        'actor_snapshot', flat=True,
    ).distinct()
    for snapshot in snapshots:
        actor_id = snapshot.get('id')
        if actor_id and actor_id not in users:
            users[actor_id] = {'id': actor_id, 'name': f"{snapshot.get('full_name', '')} (compte supprimé)"}
    return sorted(users.values(), key=lambda item: item['name'].casefold())


@require_GET
@calendar_manager_required
def history_page(request):
    paginator = Paginator(_filtered_activity(request), 30)
    page = paginator.get_page(request.GET.get('page'))
    for item in page.object_list:
        item.action_label = ACTION_LABELS.get(
            item.action, item.action.replace('_', ' ').title()
        )
    query = request.GET.copy()
    query.pop('page', None)
    return render(
        request,
        'audit/history.html',
        {
            'activity_page': page,
            'action_options': [
                (value, ACTION_LABELS.get(value, value.replace('_', ' ').title()))
                for value in ActivityLog.objects.order_by('action')
                .values_list('action', flat=True)
                .distinct()
            ],
            'entity_options': ActivityLog.objects.order_by('entity_type')
            .values_list('entity_type', flat=True)
            .distinct(),
            'user_options': _history_users(),
            'filter_query': query.urlencode(),
        },
    )


@require_GET
@calendar_manager_required
def activity_api(request):
    queryset = _filtered_activity(request)
    paginator = Paginator(queryset, 50)
    page = paginator.get_page(request.GET.get('page'))
    return JsonResponse(
        {
            'data': [
                {
                    'id': str(item.id),
                    'user': item.actor_name or None,
                    'actor_snapshot': item.actor_snapshot,
                    'action': item.action,
                    'entity_type': item.entity_type,
                    'entity_id': str(item.entity_id),
                    'old_values': item.old_values,
                    'new_values': item.new_values,
                    'created_at': item.created_at.isoformat(),
                }
                for item in page.object_list
            ],
            'pagination': {
                'page': page.number,
                'pages': paginator.num_pages,
                'count': paginator.count,
            },
        }
    )
