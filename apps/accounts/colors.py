from colorsys import hls_to_rgb

from django.core.exceptions import ValidationError

from .models import Profile


CALENDAR_PALETTE = (
    '#2563EB', '#16A34A', '#DC2626', '#9333EA', '#D97706', '#0891B2',
    '#DB2777', '#475569', '#0F766E', '#C2410C', '#4F46E5', '#A16207',
)


def available_calendar_color():
    """Suggest an unused color without changing existing member profiles."""
    used = {
        color.upper() for color in Profile.objects.filter(deleted_at__isnull=True)
        .values_list('calendar_color', flat=True)
    }
    for color in CALENDAR_PALETTE:
        if color not in used:
            return color
    # Extend the palette for larger teams, spreading hues around the color wheel.
    for lightness in (0.42, 0.34, 0.50):
        for index in range(360):
            rgb = hls_to_rgb((index * 137.508 % 360) / 360, lightness, 0.70)
            color = '#' + ''.join(f'{round(channel * 255):02X}' for channel in rgb)
            if color not in used:
                return color
    raise ValidationError({'calendar_color': 'Choisissez une couleur manuellement.'})
