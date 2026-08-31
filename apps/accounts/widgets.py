from django import forms


class CalendarColorInput(forms.TextInput):
    input_type = 'color'
    template_name = 'accounts/widgets/calendar_color.html'

    class Media:
        js = ('js/calendar-color.js',)
