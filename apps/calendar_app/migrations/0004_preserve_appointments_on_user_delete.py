from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('calendar_app', '0003_recurrenceseries_appointment_recurrence_series'),
        ('audit', '0002_activitylog_actor_snapshot'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='appointment', name='created_by',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='created_appointments', to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='appointment', name='updated_by',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='updated_appointments', to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='appointmentmember', name='user',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='appointment_links', to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
