from django import forms

from .models import Client


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ('name', 'company_name', 'phone', 'email', 'notes')
        labels = {
            'name': 'Nom du client',
            'company_name': 'Entreprise',
            'phone': 'Téléphone',
            'email': 'Adresse e-mail',
            'notes': 'Notes internes',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Nom et prénom'}),
            'company_name': forms.TextInput(attrs={'placeholder': 'Entreprise (optionnel)'}),
            'phone': forms.TextInput(attrs={'placeholder': '+216 ...'}),
            'email': forms.EmailInput(attrs={'placeholder': 'client@entreprise.com'}),
            'notes': forms.Textarea(
                attrs={'rows': 5, 'placeholder': 'Informations utiles pour l’équipe'}
            ),
        }

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if len(name) < 2:
            raise forms.ValidationError('Le nom doit contenir au moins 2 caractères.')
        return name
