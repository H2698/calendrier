from django.contrib import admin

from .models import Client


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'company_name', 'phone', 'email', 'archived_at')
    list_filter = ('archived_at',)
    search_fields = ('name', 'company_name', 'phone', 'email')
    readonly_fields = ('id', 'created_at', 'updated_at', 'archived_at')

# Register your models here.
