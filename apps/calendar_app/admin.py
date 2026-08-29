from django.contrib import admin

from .models import Appointment, AppointmentMember, AppointmentType


@admin.register(AppointmentType)
class AppointmentTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'updated_at')
    list_filter = ('is_active',)


class AppointmentMemberInline(admin.TabularInline):
    model = AppointmentMember
    extra = 0


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('title', 'appointment_type', 'start_at', 'end_at', 'status')
    list_filter = ('status', 'appointment_type')
    search_fields = ('title', 'client__name')
    inlines = (AppointmentMemberInline,)

# Register your models here.
