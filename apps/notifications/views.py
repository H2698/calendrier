import json
import hmac

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import Notification, PushSubscription
from .services import dispatch_due_notifications


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
    if not user.profile.in_app_notifications_enabled:
        return user.notifications.none()
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
        {
            'notifications': queryset[:100],
            'unread_only': unread_only,
            'push_public_key': settings.VAPID_PUBLIC_KEY,
            'push_configured': bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY),
        },
    )


@require_GET
def service_worker(request):
    response = HttpResponse(
        render_to_string('notifications/service-worker.js'),
        content_type='application/javascript',
    )
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Service-Worker-Allowed'] = '/'
    return response


@require_GET
def send_due_notifications_api(request):
    expected = settings.CRON_SECRET
    supplied = request.headers.get('Authorization', '').removeprefix('Bearer ').strip()
    if not expected or not hmac.compare_digest(supplied, expected):
        return JsonResponse({'error': 'forbidden'}, status=403)
    return JsonResponse({'ok': True, 'processed': dispatch_due_notifications()})


@require_http_methods(['GET', 'POST', 'DELETE'])
def push_subscription_api(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'authentication_required'}, status=401)
    if request.method == 'GET':
        return JsonResponse(
            {
                'configured': bool(
                    settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY
                ),
                'public_key': settings.VAPID_PUBLIC_KEY,
                'subscription_count': request.user.push_subscriptions.count(),
            }
        )
    try:
        data = json.loads(request.body or b'{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_json'}, status=400)

    endpoint = data.get('endpoint', '') if isinstance(data, dict) else ''
    if request.method == 'DELETE':
        deleted, _ = request.user.push_subscriptions.filter(endpoint=endpoint).delete()
        if not request.user.push_subscriptions.exists():
            request.user.profile.browser_notifications_enabled = False
            request.user.profile.save(
                update_fields=('browser_notifications_enabled', 'updated_at')
            )
        return JsonResponse({'ok': True, 'deleted': bool(deleted)})

    keys = data.get('keys', {}) if isinstance(data, dict) else {}
    if not endpoint or not isinstance(keys, dict) or not keys.get('p256dh') or not keys.get('auth'):
        return JsonResponse({'error': 'invalid_subscription'}, status=400)
    try:
        URLValidator(schemes=('https',))(endpoint)
    except ValidationError:
        return JsonResponse({'error': 'invalid_endpoint'}, status=400)

    subscription, created = PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            'user': request.user,
            'p256dh': keys['p256dh'],
            'auth': keys['auth'],
            'user_agent': request.headers.get('User-Agent', '')[:1000],
        },
    )
    if not request.user.profile.browser_notifications_enabled:
        request.user.profile.browser_notifications_enabled = True
        request.user.profile.save(update_fields=('browser_notifications_enabled', 'updated_at'))
    return JsonResponse(
        {'ok': True, 'created': created, 'id': str(subscription.id)},
        status=201 if created else 200,
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
