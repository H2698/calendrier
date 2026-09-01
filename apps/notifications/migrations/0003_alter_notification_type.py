from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('notifications', '0002_pushsubscription'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='type',
            field=models.CharField(
                choices=[
                    ('appointment_created', 'Rendez-vous créé'),
                    ('appointment_updated', 'Rendez-vous modifié'),
                    ('appointment_cancelled', 'Rendez-vous annulé'),
                    ('appointment_reminder', 'Rappel rendez-vous'),
                    ('report_required', 'Rapport à rédiger'),
                ],
                db_index=True,
                max_length=40,
            ),
        ),
    ]
