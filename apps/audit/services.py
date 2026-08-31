from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from .models import ActivityLog


def json_safe(value):
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    return value


def actor_identity(actor):
    if not actor:
        return {}
    profile = getattr(actor, 'profile', None)
    return {
        'id': str(actor.pk),
        'full_name': profile.full_name if profile else actor.get_full_name(),
        'email': actor.email,
        'role': profile.role if profile else '',
    }


def log_activity(*, actor, action, entity_type, entity_id, old_values=None, new_values=None):
    return ActivityLog.objects.create(
        user=actor,
        actor_snapshot=actor_identity(actor),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_values=json_safe(old_values or {}),
        new_values=json_safe(new_values or {}),
    )
