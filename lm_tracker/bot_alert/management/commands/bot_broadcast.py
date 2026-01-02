from django.core.management.base import BaseCommand

from lm_tracker.bot_alert.services.broadcast import run_broadcast


class Command(BaseCommand):
    help = "Fetch harga dan broadcast ke Telegram"

    def handle(self, *args, **options):
        run_broadcast()
        self.stdout.write(self.style.SUCCESS("Done"))
