import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('calendar_app', '0004_preserve_appointments_on_user_delete'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AppointmentReport',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('author_name', models.CharField(max_length=150)),
                ('author_email', models.EmailField(max_length=254)),
                ('content', models.TextField(max_length=10000)),
                ('submitted_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('appointment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reports', to='calendar_app.appointment')),
                ('author', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='appointment_reports', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('submitted_at',),
                'indexes': [models.Index(fields=['appointment', 'submitted_at'], name='report_appt_submitted_idx')],
                'constraints': [models.UniqueConstraint(fields=('appointment', 'author'), name='unique_appointment_report_author')],
            },
        ),
    ]
