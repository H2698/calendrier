from django import forms


class AppointmentReportForm(forms.Form):
    content = forms.CharField(
        label='Votre rapport', min_length=10, max_length=10000,
        widget=forms.Textarea(attrs={
            'rows': 9,
            'placeholder': 'Résultats, décisions, actions à suivre…',
        }),
    )
