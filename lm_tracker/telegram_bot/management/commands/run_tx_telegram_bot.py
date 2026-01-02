from django.core.management.base import BaseCommand

from lm_tracker.telegram_bot.telegram_app import build_app


class Command(BaseCommand):
    help = "Run Telegram bot untuk pencatatan transaksi emas/perak"

    def handle(self, *args, **options):
        application = build_app()
        self.stdout.write(self.style.SUCCESS("Bot running (polling). Ctrl+C to stop."))
        application.run_polling()
