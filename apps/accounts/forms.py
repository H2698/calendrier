from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        label='Adresse e-mail',
        widget=forms.EmailInput(
            attrs={
                'autocomplete': 'email',
                'autofocus': True,
                'placeholder': 'nom@agence.com',
            }
        ),
    )
    password = forms.CharField(
        label='Mot de passe',
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                'autocomplete': 'current-password',
                'placeholder': 'Votre mot de passe',
            }
        ),
    )

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        profile = getattr(user, 'profile', None)
        if not profile or not profile.is_active:
            raise ValidationError(
                'Ce compte est désactivé.',
                code='inactive',
            )


class TeamMemberForm(forms.Form):
    full_name = forms.CharField(label='Nom complet', max_length=150)
    email = forms.EmailField(label='Adresse e-mail')
    password = forms.CharField(label='Mot de passe initial', min_length=10, widget=forms.PasswordInput)
    role = forms.ChoiceField(label='Rôle', choices=(('manager', 'Gérante'), ('member', 'Membre')))
    calendar_color = forms.RegexField(label='Couleur calendrier', regex=r'^#[0-9A-Fa-f]{6}$', initial='#2563EB')
