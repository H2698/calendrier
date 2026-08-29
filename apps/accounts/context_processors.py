from django.utils import timezone

from .permissions import user_role


def account_context(request):
    role = user_role(request.user)
    unread_notifications = 0
    if request.user.is_authenticated:
        unread_notifications = request.user.notifications.filter(
            is_read=False,
            scheduled_for__lte=timezone.now(),
        ).count()
    return {
        'current_role': role,
        'can_manage_calendar': role in {'admin', 'manager'},
        'is_agency_admin': role == 'admin',
        'unread_notifications': unread_notifications,
    }
