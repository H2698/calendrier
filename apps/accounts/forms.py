from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from apps.calendar_app.models import AppointmentType
from apps.core.models import AgencySettings

from .models import Profile
from .colors import available_calendar_color
from .widgets import CalendarColorInput


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
    calendar_color = forms.RegexField(
        label='Couleur calendrier', regex=r'^#[0-9A-Fa-f]{6}$',
        required=False, widget=CalendarColorInput,
    )
    automatic_color = forms.BooleanField(
        label='Choisir automatiquement une couleur disponible', required=False, initial=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        suggested = available_calendar_color()
        self.fields['calendar_color'].initial = suggested
        self.fields['calendar_color'].widget.attrs['data-suggested-color'] = suggested

    def clean(self):
        data = super().clean()
        if data.pop('automatic_color', False):
            # Recompute on creation: another admin may have used the preview color.
            data['calendar_color'] = None
        elif not data.get('calendar_color') and 'calendar_color' not in self.errors:
            self.add_error('calendar_color', 'Choisissez une couleur ou activez le choix automatique.')
        return data


class TeamMemberEditForm(forms.Form):
    full_name = forms.CharField(label='Nom complet', max_length=150)
    email = forms.EmailField(label='Adresse e-mail')
    role = forms.ChoiceField(label='Rôle', choices=Profile.Role.choices)
    calendar_color = forms.RegexField(
        label='Couleur calendrier', regex=r'^#[0-9A-Fa-f]{6}$', widget=CalendarColorInput,
    )
    is_active = forms.BooleanField(label='Compte actif', required=False)


class ProfileSettingsForm(forms.ModelForm):
    email = forms.EmailField(label='Adresse e-mail', required=True, max_length=150)

    class Meta:
        model = Profile
        fields = ('full_name', 'email', 'calendar_color', 'avatar_url')
        widgets = {'calendar_color': CalendarColorInput}
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


class InitialDataSetupForm(AgencySettingsForm):
    appointment_types = forms.CharField(
        label='Types de rendez-vous',
        required=False,
        help_text='Un type par ligne. Les types existants sont conservés.',
        widget=forms.Textarea(attrs={
            'rows': 8,
            'placeholder': 'Réunion client\nShooting\nRéunion interne',
        }),
    )

    class Meta(AgencySettingsForm.Meta):
        fields = (*AgencySettingsForm.Meta.fields, 'appointment_types')

    def clean_appointment_types(self):
        raw_names = self.cleaned_data['appointment_types']
        names = []
        seen = set()
        for raw_name in raw_names.splitlines():
            name = raw_name.strip()
            if not name:
                continue
            if len(name) > 100:
                raise ValidationError(
                    'Chaque type de rendez-vous doit contenir au maximum 100 caractères.'
                )
            normalized = name.casefold()
            if normalized not in seen:
                names.append(name)
                seen.add(normalized)
        if not names:
            raise ValidationError('Ajoutez au moins un type de rendez-vous.')
        if len(names) > 30:
            raise ValidationError('Vous pouvez initialiser au maximum 30 types à la fois.')
        return names


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
