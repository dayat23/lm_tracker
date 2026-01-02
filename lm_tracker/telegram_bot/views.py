import json

from django.conf import settings
from django.http import HttpResponse
from django.http import HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from telegram import Update

from .telegram_app import build_app


@csrf_exempt
async def telegram_webhook(request, secret_path: str):
    # Optional: secret path check (you can hardcode it in URL)
    # e.g. /telegram/webhook/<secret_path>/
    # If you don't want secret_path, remove it from urls.

    # Verify secret header (recommended)
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if (
        settings.TELEGRAM_WEBHOOK_SECRET_TOKEN
        and secret_header != settings.TELEGRAM_WEBHOOK_SECRET_TOKEN
    ):
        return HttpResponseForbidden("invalid secret token")

    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError as err:
        return HttpResponse(str(err))

    app = build_app()
    update = Update.de_json(data, app.bot)
    await app.process_update(update)
    return HttpResponse("ok")
