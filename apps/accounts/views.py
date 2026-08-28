from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import render

from .forms import EmailAuthenticationForm


class AgencyLoginView(LoginView):
    authentication_form = EmailAuthenticationForm
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True


@login_required
def dashboard(request):
    return render(request, 'dashboard.html')
