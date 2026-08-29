from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Client


EDITABLE_FIELDS = ('name', 'company_name', 'phone', 'email', 'notes')


def _validated_values(data):
    return {field: data[field] for field in EDITABLE_FIELDS if field in data}


@transaction.atomic
def create_client(*, actor, data):
    client = Client(created_by=actor, **_validated_values(data))
    client.full_clean()
    client.save()
    return client


@transaction.atomic
def update_client(*, client, data):
    if client.is_archived:
        raise ValidationError('Un client archivé ne peut pas être modifié.')
    values = _validated_values(data)
    for field, value in values.items():
        setattr(client, field, value)
    client.full_clean()
    client.save()
    return client


@transaction.atomic
def archive_client(*, client):
    if not client.is_archived:
        client.archived_at = timezone.now()
        client.save(update_fields=('archived_at', 'updated_at'))
    return client
