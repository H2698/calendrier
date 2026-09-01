import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.clients.models import Client


class AppointmentType(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_appointment_types',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name


class RecurrenceSeries(models.Model):
    class Frequency(models.TextChoices):
        DAILY = 'daily', 'Chaque jour'
        WEEKLY = 'weekly', 'Chaque semaine'
        MONTHLY = 'monthly', 'Chaque mois'
        CUSTOM = 'custom', 'Personnalisée'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    frequency = models.CharField(max_length=16, choices=Frequency.choices)
    interval_value = models.PositiveSmallIntegerField(default=1)
    days_of_week = models.JSONField(default=list, blank=True)
    end_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.interval_value < 1:
            raise ValidationError({'interval_value': 'L’intervalle doit être positif.'})
        invalid_days = set(self.days_of_week) - set(range(7))
        if invalid_days:
            raise ValidationError({'days_of_week': 'Les jours doivent être compris entre 0 et 6.'})
        if self.frequency == self.Frequency.CUSTOM and not self.days_of_week:
            raise ValidationError({'days_of_week': 'Choisissez au moins un jour.'})


class Appointment(models.Model):
    class Status(models.TextChoices):
        PLANNED = 'planned', 'Planifié'
        CONFIRMED = 'confirmed', 'Confirmé'
        COMPLETED = 'completed', 'Terminé'
        CANCELLED = 'cancelled', 'Annulé'
        POSTPONED = 'postponed', 'Reporté'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='appointments',
    )
    appointment_type = models.ForeignKey(
        AppointmentType,
        on_delete=models.PROTECT,
        related_name='appointments',
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    start_at = models.DateTimeField(db_index=True)
    end_at = models.DateTimeField(db_index=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PLANNED,
        db_index=True,
    )
    notes = models.TextField(blank=True)
    recurrence_series = models.ForeignKey(
        RecurrenceSeries,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='appointments',
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='AppointmentMember',
        related_name='appointments',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_appointments',
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_appointments',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ('start_at',)
        indexes = [
            models.Index(fields=('start_at', 'end_at')),
            models.Index(fields=('status', 'start_at')),
            models.Index(fields=('deleted_at', 'start_at')),
        ]

    def clean(self):
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValidationError({'end_at': 'La fin doit être après le début.'})

    def save(self, *args, **kwargs):
        self.title = self.title.strip()
        super().save(*args, **kwargs)

    @property
    def is_cancelled(self):
        return self.status == self.Status.CANCELLED

    def __str__(self):
        return self.title


class AppointmentMember(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.CASCADE,
        related_name='member_links',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='appointment_links',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('appointment', 'user'),
                name='unique_appointment_member',
            )
        ]
        indexes = [models.Index(fields=('user', 'appointment'))]

    def __str__(self):
        return f'{self.appointment} · {self.user}'


class AppointmentReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.ForeignKey(
        Appointment, on_delete=models.CASCADE, related_name='reports',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='appointment_reports',
    )
    author_name = models.CharField(max_length=150)
    author_email = models.EmailField()
    content = models.TextField(max_length=10000)
    submitted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ('submitted_at',)
        constraints = [models.UniqueConstraint(
            fields=('appointment', 'author'), name='unique_appointment_report_author',
        )]
        indexes = [models.Index(
            fields=('appointment', 'submitted_at'),
            name='report_appt_submitted_idx',
        )]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Un rapport envoyé ne peut pas être modifié.')
        self.content = self.content.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.appointment} · {self.author_name}'
