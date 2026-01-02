import secrets
from datetime import timedelta

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone

from .models import ActivationToken


def checkout(request):
    """
    Simulasi: user klik link /billing/checkout/?tg=<telegram_user_id>
    Anggap "sudah bayar", langsung buat activation token lalu redirect ke success.
    """
    tg = request.GET.get("tg", "")
    if not tg.isdigit():
        return HttpResponse("invalid")

    token = secrets.token_urlsafe(24)
    ActivationToken.objects.create(
        token=token,
        plan="PRO",
        expires_at=timezone.now() + timedelta(hours=2),
    )
    return redirect(f"{settings.APP_BASE_URL}/billing/success/?token={token}")


def success(request):
    token = request.GET.get("token", "")
    deeplink = f"https://t.me/{_bot_username_guess()}?start=paid_{token}"
    return HttpResponse(
        f"Pembayaran sukses (simulasi). Klik untuk aktivasi PRO di Telegram: "
        f"<a href='{deeplink}'>{deeplink}</a>",
        content_type="text/html",
    )


def _bot_username_guess():
    # isi manual agar rapi (recommended), atau set BOT_USERNAME env
    return getattr(settings, "TELEGRAM_BOT_USERNAME", "logam_track_bot")
