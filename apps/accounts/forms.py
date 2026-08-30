from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from apps.calendar_app.models import AppointmentType
from apps.core.models import AgencySettings

from .models import Profile


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


class TeamMemberEditForm(forms.Form):
    full_name = forms.CharField(label='Nom complet', max_length=150)
    email = forms.EmailField(label='Adresse e-mail')
    role = forms.ChoiceField(label='Rôle', choices=Profile.Role.choices)
    calendar_color = forms.RegexField(
        label='Couleur calendrier', regex=r'^#[0-9A-Fa-f]{6}$'
    )
    is_active = forms.BooleanField(label='Compte actif', required=False)


class ProfileSettingsForm(forms.ModelForm):
    email = forms.EmailField(label='Adresse e-mail', required=True, max_length=150)

    class Meta:
        model = Profile
        fields = ('full_name', 'email', 'calendar_color', 'avatar_url')
        labels = {
            'full_name': 'Nom complet',
            'calendar_color': 'Couleur calendrier',
            'avatar_url': 'URL de la photo',
        }

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()

    def save(self, commit=True):
        profile = super().save(commit=commit)
        if commit:
            profile.user.email = profile.email
            profile.user.username = profile.email
            profile.user.save(update_fields=('email', 'username'))
        return profile


class AgencySettingsForm(forms.ModelForm):
    class Meta:
        model = AgencySettings
        fields = ('agency_name', 'logo_url', 'timezone', 'reminder_minutes')
        labels = {
            'agency_name': 'Nom de l’agence',
            'logo_url': 'URL du logo',
            'timezone': 'Fuseau horaire',
            'reminder_minutes': 'Rappel par défaut (minutes)',
        }

    def clean_timezone(self):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        value = self.cleaned_data['timezone'].strip()
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValidationError('Fuseau horaire IANA invalide.') from exc
        return value

    def clean_reminder_minutes(self):
        value = self.cleaned_data['reminder_minutes']
        if value < 1 or value > 1440:
            raise ValidationError('Le rappel doit être compris entre 1 et 1440 minutes.')
        return value


class AppointmentTypeSettingsForm(forms.ModelForm):
    class Meta:
        model = AppointmentType
        fields = ('name',)
        labels = {'name': 'Nouveau type de rendez-vous'}


class NotificationSettingsForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ('in_app_notifications_enabled',)
        labels = {'in_app_notifications_enabled': 'Notifications dans l’application'}
