from django.core.management.base import BaseCommand
from apps.notifications.services import dispatch_due_notifications


class Command(BaseCommand):
    help = 'Mark due internal reminders as sent (Web Push is added in Phase 10).'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS(f'{dispatch_due_notifications()} notification(s) envoyée(s).'))
