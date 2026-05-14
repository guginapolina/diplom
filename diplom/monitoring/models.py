from django.db import models
from django.contrib.auth.models import User

class Facility(models.Model):
    name = models.CharField(max_length=200)
    address = models.TextField()
    owner = models.ForeignKey(User, on_delete=models.CASCADE)

class Device(models.Model):
    serial_number = models.CharField(max_length=50, unique=True)
    model_name = models.CharField(max_length=100)
    facility = models.ForeignKey(Facility, on_delete=models.SET_NULL, null=True)
    is_online = models.BooleanField(default=False)

class TelemetryLog(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    temperature = models.FloatField()
    voltage = models.FloatField()

class Alert(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    message = models.TextField()
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

class ServiceTicket(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    description = models.TextField()
    status = models.CharField(max_length=20, default='New') # New, In Progress, Closed
    engineer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='assigned_tickets')


class SupportTicket(models.Model):
    STATUS_CHOICES = [
        ('new', 'Новая (Ожидает)'),
        ('in_progress', 'В работе у инженера'),
        ('resolved', 'Решено'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Пользователь")

    title = models.CharField(max_length=200, verbose_name="Краткая суть проблемы")
    description = models.TextField(verbose_name="Подробное описание")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new', verbose_name="Статус")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    def __str__(self):
        return f"Заявка #{self.id} от {self.user.username} - {self.title}"

class Specialist(models.Model):
    fio = models.CharField(max_length=200, verbose_name="ФИО специалиста")
    phone = models.CharField(max_length=20, verbose_name="Телефон")

    def __str__(self):
        return self.fio


class ClientDevice(models.Model):
    DEVICE_CHOICES = [
        ('thermostat', 'GSM-термостат'),
        ('controller', 'Контроллер отопления'),
        ('tracker', 'Автомобильный трекер'),
        ('security', 'Охранная система'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='additional_devices')
    device_type = models.CharField(max_length=50, choices=DEVICE_CHOICES)
    serial_number = models.CharField(max_length=100, unique=True)
    added_at = models.DateTimeField(auto_now_add=True)

    last_metric = models.FloatField(null=True, blank=True, verbose_name="Последняя метрика")
    last_metric_time = models.DateTimeField(auto_now=True, null=True)

    def __str__(self):
        return f"{self.serial_number} ({self.user.username})"

class AppointmentSlot(models.Model):
    specialist = models.ForeignKey(Specialist, on_delete=models.CASCADE, related_name='slots')
    date = models.DateField(verbose_name="Дата")
    time = models.TimeField(verbose_name="Время начала (слот 2 часа)")
    is_booked = models.BooleanField(default=False, verbose_name="Занято клиентом")

    ticket = models.OneToOneField('SupportTicket', on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='appointment', verbose_name="Связанная заявка")

    def __str__(self):
        return f"{self.specialist.fio} - {self.date} {self.time}"

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    fio = models.CharField(max_length=255, verbose_name="ФИО")
    phone = models.CharField(max_length=20, verbose_name="Телефон")

    DEVICE_TYPES = [
        ('thermostat', 'GSM-термостат'),
        ('controller', 'Контроллер отопления'),
        ('tracker', 'Автомобильный трекер'),
        ('security', 'Охранная система'),
    ]
    device_type = models.CharField(max_length=50, choices=DEVICE_TYPES, verbose_name="Тип оборудования")
    serial_number = models.CharField(max_length=100, verbose_name="Серийный номер")

    is_approved = models.BooleanField(default=False, verbose_name="Аккаунт подтвержден")

    last_metric = models.FloatField(null=True, blank=True, verbose_name="Последняя метрика")
    last_metric_time = models.DateTimeField(auto_now=True, null=True)

    def __str__(self):
        return f"{self.fio} ({self.user.username})"
