from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError
from django.utils import timezone

from .models import AgencySettings


class AgencyTimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        zone_name = cache.get('agency_timezone')
        if not zone_name:
            try:
                zone_name = (
                    AgencySettings.objects.values_list('timezone', flat=True).first()
                    or settings.TIME_ZONE
                )
            except DatabaseError:
                zone_name = settings.TIME_ZONE
            cache.set('agency_timezone', zone_name, 300)
        try:
            timezone.activate(ZoneInfo(zone_name))
        except ZoneInfoNotFoundError:
            timezone.activate(ZoneInfo(settings.TIME_ZONE))
        return self.get_response(request)
