from django.contrib import admin
from .models import Profile, SupportTicket, Facility, Device, TelemetryLog, Alert, ServiceTicket


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('fio', 'user', 'phone', 'device_type', 'serial_number', 'is_approved')

    list_editable = ('is_approved',)

    list_filter = ('is_approved', 'device_type')

    search_fields = ('fio', 'serial_number', 'user__username')


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'title', 'status', 'created_at')

    list_editable = ('status',)

    list_filter = ('status', 'created_at')

    search_fields = ('title', 'description', 'user__username')


admin.site.register(Facility)
admin.site.register(Device)
admin.site.register(TelemetryLog)
admin.site.register(Alert)
admin.site.register(ServiceTicket)