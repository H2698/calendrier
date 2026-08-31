from django.contrib import admin

from .models import ActivityLog


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'entity_type', 'entity_id', 'user', 'created_at')
    list_filter = ('action', 'entity_type')
    search_fields = ('entity_id', 'user__email')
    readonly_fields = (
        'id',
        'user',
        'actor_snapshot',
        'action',
        'entity_type',
        'entity_id',
        'old_values',
        'new_values',
        'created_at',
    )

# Register your models here.
