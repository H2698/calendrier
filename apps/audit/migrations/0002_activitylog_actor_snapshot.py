from django.db import migrations, models


def snapshot_existing_actors(apps, schema_editor):
    ActivityLog = apps.get_model('audit', 'ActivityLog')
    Profile = apps.get_model('accounts', 'Profile')
    alias = schema_editor.connection.alias
    profiles = {
        profile.user_id: profile
        for profile in Profile.objects.using(alias).all()
    }
    for log in ActivityLog.objects.using(alias).filter(
        user__isnull=False, actor_snapshot={},
    ).select_related('user').iterator():
        user = log.user
        profile = profiles.get(user.pk)
        ActivityLog.objects.using(alias).filter(pk=log.pk).update(actor_snapshot={
            'id': str(user.pk),
            'full_name': profile.full_name if profile else f'{user.first_name} {user.last_name}'.strip(),
            'email': user.email,
            'role': profile.role if profile else '',
        })


class Migration(migrations.Migration):
    dependencies = [
        ('audit', '0001_initial'),
        ('accounts', '0004_profile_deleted_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='activitylog', name='actor_snapshot',
            field=models.JSONField(blank=True, default=dict, db_default={}),
        ),
        migrations.RunPython(snapshot_existing_actors, migrations.RunPython.noop),
    ]
