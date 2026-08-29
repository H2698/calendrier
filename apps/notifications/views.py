from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import Notification


def payload(item):
    return {
        'id': str(item.id),
        'type': item.type,
        'title': item.title,
        'message': item.message,
        'is_read': item.is_read,
        'appointment_id': str(item.appointment_id) if item.appointment_id else None,
        'scheduled_for': item.scheduled_for.isoformat() if item.scheduled_for else None,
        'sent_at': item.sent_at.isoformat() if item.sent_at else None,
        'created_at': item.created_at.isoformat(),
    }


def visible_notifications(user):
    return user.notifications.filter(scheduled_for__lte=timezone.now())


@login_required
def notifications_page(request):
    queryset = visible_notifications(request.user).select_related('appointment')
    unread_only = request.GET.get('view') == 'unread'
    if unread_only:
        queryset = queryset.filter(is_read=False)
    return render(
        request,
        'notifications/notifications.html',
        {'notifications': queryset[:100], 'unread_only': unread_only},
    )


@require_GET
def notifications_api(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'authentication_required'}, status=401)
    queryset = visible_notifications(request.user)
    if request.GET.get('unread') == 'true':
        queryset = queryset.filter(is_read=False)
    return JsonResponse(
        {
            'data': [payload(item) for item in queryset[:100]],
            'unread_count': visible_notifications(request.user).filter(is_read=False).count(),
        }
    )


@require_POST
def notification_read_api(request, notification_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'authentication_required'}, status=401)
    item = get_object_or_404(Notification, id=notification_id, user=request.user)
    item.is_read = True
    item.save(update_fields=('is_read',))
    return JsonResponse({'data': payload(item)})


@require_POST
def notifications_read_all_api(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'authentication_required'}, status=401)
    updated = visible_notifications(request.user).filter(is_read=False).update(is_read=True)
    return JsonResponse({'ok': True, 'updated': updated})
