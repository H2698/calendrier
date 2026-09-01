from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('calendar_app', '0005_appointmentreport'),
    ]

    operations = [
        migrations.AlterField(
            model_name='appointment',
            name='status',
            field=models.CharField(
                choices=[
                    ('planned', 'Planifié'),
                    ('confirmed', 'Confirmé'),
                    ('completed', 'Terminé'),
                    ('cancelled', 'Annulé'),
                ],
                db_index=True,
                default='planned',
                max_length=16,
            ),
        ),
    ]
