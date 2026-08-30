from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import log_activity

from .models import Client


EDITABLE_FIELDS = ('name', 'company_name', 'phone', 'email', 'notes')


def _validated_values(data):
    return {field: data[field] for field in EDITABLE_FIELDS if field in data}


def _client_snapshot(client):
    return {field: getattr(client, field) for field in EDITABLE_FIELDS} | {
        'archived_at': client.archived_at
    }


@transaction.atomic
def create_client(*, actor, data):
    client = Client(created_by=actor, **_validated_values(data))
    client.full_clean()
    client.save()
    log_activity(
        actor=actor, action='client_created', entity_type='client',
        entity_id=client.id, new_values=_client_snapshot(client),
    )
    return client


@transaction.atomic
def update_client(*, client, data, actor=None):
    if client.is_archived:
        raise ValidationError('Un client archivé ne peut pas être modifié.')
    old_values = _client_snapshot(client)
    values = _validated_values(data)
    for field, value in values.items():
        setattr(client, field, value)
    client.full_clean()
    client.save()
    log_activity(
        actor=actor, action='client_updated', entity_type='client',
        entity_id=client.id, old_values=old_values,
        new_values=_client_snapshot(client),
    )
    return client


@transaction.atomic
def archive_client(*, client, actor=None):
    if not client.is_archived:
        old_values = _client_snapshot(client)
        client.archived_at = timezone.now()
        client.save(update_fields=('archived_at', 'updated_at'))
        log_activity(
            actor=actor, action='client_archived', entity_type='client',
            entity_id=client.id, old_values=old_values,
            new_values=_client_snapshot(client),
        )
    return client
