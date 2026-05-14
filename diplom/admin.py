from django.contrib import admin
from monitoring.models import Profile

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('fio', 'device_type', 'serial_number', 'is_approved')
    list_filter = ('is_approved', 'device_type')
    search_fields = ('fio', 'serial_number')
    list_editable = ('is_approved',)