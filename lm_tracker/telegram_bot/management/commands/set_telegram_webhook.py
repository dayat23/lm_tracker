from django.conf import settings
from django.core.management.base import BaseCommand
from telegram import Bot


class Command(BaseCommand):
    help = "Set Telegram webhook to Django endpoint"

    def handle(self, *args, **options):
        bot = Bot(settings.TELEGRAM_BOT_TOKEN)
        url = settings.PUBLIC_WEBHOOK_URL
        secret = settings.TELEGRAM_WEBHOOK_SECRET_TOKEN

        if not url:
            self.stderr.write("PUBLIC_WEBHOOK_URL is empty")
            return

        bot.set_webhook(url=url, secret_token=secret or None)
        self.stdout.write(f"Webhook set: {url}")
