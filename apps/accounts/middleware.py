from django.contrib.auth import SESSION_KEY, logout
from django.shortcuts import redirect
from django.urls import reverse


class ActiveAccountMiddleware:
    """End existing sessions as soon as an internal account is disabled."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated and SESSION_KEY in request.session:
            # A permanently deleted user no longer resolves in the backend.
            logout(request)
            if request.path != reverse('accounts:login'):
                return redirect('accounts:login')
        if request.user.is_authenticated:
            profile = getattr(request.user, 'profile', None)
            if not request.user.is_active or not profile or not profile.is_active or profile.deleted_at:
                logout(request)
                if request.path != reverse('accounts:login'):
                    return redirect('accounts:login')
        return self.get_response(request)
