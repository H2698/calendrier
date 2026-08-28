from django.contrib import admin

from .models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'email', 'role', 'is_active', 'calendar_color')
    list_filter = ('role', 'is_active')
    search_fields = ('full_name', 'email', 'user__username')
    readonly_fields = ('id', 'created_at', 'updated_at')

# Register your models here.
