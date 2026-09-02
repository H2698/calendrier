from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='agencysettings',
            name='setup_completed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
