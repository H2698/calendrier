from django.core.paginator import Paginator
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.accounts.permissions import calendar_manager_required

from .models import ActivityLog


@require_GET
@calendar_manager_required
def activity_api(request):
    queryset = ActivityLog.objects.select_related('user', 'user__profile')
    if action := request.GET.get('action'):
        queryset = queryset.filter(action=action)
    if entity_type := request.GET.get('entity_type'):
        queryset = queryset.filter(entity_type=entity_type)
    paginator = Paginator(queryset, 50)
    page = paginator.get_page(request.GET.get('page'))
    return JsonResponse(
        {
            'data': [
                {
                    'id': str(item.id),
                    'user': item.user.profile.full_name if item.user else None,
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
