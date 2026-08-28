from .permissions import user_role


def account_context(request):
    role = user_role(request.user)
    return {
        'current_role': role,
        'can_manage_calendar': role in {'admin', 'manager'},
        'is_agency_admin': role == 'admin',
    }
