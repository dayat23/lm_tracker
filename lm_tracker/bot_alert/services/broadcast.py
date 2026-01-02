from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from lm_tracker.bot_alert.models import BroadcastLog
from lm_tracker.bot_alert.models import PriceSnapshot
from lm_tracker.bot_alert.services.providers import calc_spot_idr_per_gram
from lm_tracker.bot_alert.services.providers import fetch_antam_1g_prices
from lm_tracker.bot_alert.services.providers import fetch_buyback
from lm_tracker.bot_alert.services.providers import get_spot_world
from lm_tracker.bot_alert.services.telegram import send_telegram

FOUR_LEN = 4
NINE_LEN = 9


def fmt_rp(n: float) -> str:
    n_int = round(n)
    return "Rp " + f"{n_int:,}".replace(",", ".")


def fmt_num_us(n: float, d=2) -> str:
    return f"{n:,.{d}f}"


def fmt_pct(p):
    if p is None:
        return "-"
    sign = "+" if p >= 0 else ""
    return f"{sign}{p:.2f}%"


def pct_change(new: float, old: float | None):
    if old is None or old == 0:
        return None
    return (new - old) / old * 100.0


def parse_slots():
    slots = [s.strip() for s in settings.UPDATE_SLOTS.split(",") if s.strip()]
    return slots or ["09:00", "13:00", "19:00"]


def current_slot():
    now = timezone.localtime()
    for slot in parse_slots():
        hh, mm = map(int, slot.split(":"))
        # window 10 menit pertama untuk cron tiap 10 menit
        if now.hour == hh and mm == 0 and 0 <= now.minute <= NINE_LEN:
            return slot
        # fleksibel untuk slot non-00
        if now.hour == hh and abs(now.minute - mm) <= FOUR_LEN:
            return slot
    return None


def can_send(last_sent_at, cooldown_min: int):
    if not last_sent_at:
        return True
    return (timezone.now() - last_sent_at).total_seconds() >= cooldown_min * 60


def run_broadcast():
    # 1) ambil data
    antam_base, antam_pph = fetch_antam_1g_prices()
    buyback, buyback_ts = fetch_buyback()

    xauusd, usdidr, spot_source = get_spot_world(
        settings.TWELVEDATA_API_KEY,
        settings.GOLDAPI_KEY,
    )
    spot_idr_gr = calc_spot_idr_per_gram(xauusd, usdidr)

    snap = PriceSnapshot.objects.create(
        xauusd=xauusd,
        usdidr=usdidr,
        spot_idr_gr=spot_idr_gr,
        antam_1g_base=antam_base,
        antam_1g_pph=antam_pph,
        buyback=buyback,
        buyback_ts=buyback_ts,
        spot_source=spot_source,
    )

    prev = PriceSnapshot.objects.exclude(id=snap.id).order_by("-ts").first()
    spot_pct = pct_change(snap.xauusd, prev.xauusd if prev else None)
    fx_pct = pct_change(snap.usdidr, prev.usdidr if prev else None)
    buyback_delta = (snap.buyback - prev.buyback) if prev else None

    icon = "▽"
    spot_icon_show = "Δ"
    fx_icon_show = "Δ"
    bb_icon_show = "Δ"

    if fx_pct and fx_pct < 0:
        fx_icon_show = icon

    if spot_pct and spot_pct < 0:
        spot_icon_show = icon

    if buyback_delta and buyback_delta < 0:
        bb_icon_show = icon

    # 2) cek update rutin
    slot = current_slot()
    if slot:
        slot_key = f"{timezone.localdate().isoformat()}@{slot}"
        already = BroadcastLog.objects.filter(
            kind=BroadcastLog.KIND_UPDATE,
            slot_key=slot_key,
        ).exists()
        last_update = (
            BroadcastLog.objects.filter(kind=BroadcastLog.KIND_UPDATE)
            .order_by("-sent_at")
            .first()
        )
        if (not already) and can_send(
            last_update.sent_at if last_update else None,
            settings.COOLDOWN_UPDATE_MIN,
        ):
            spread = snap.antam_1g_base - snap.buyback
            update_tz = timezone.localtime().strftime("%d %b %Y %H:%M WIB")
            msg = "\n".join(
                [
                    f"[UPDATE EMAS] {update_tz}",
                    "",
                    "Spot Dunia (XAU/USD)",
                    f"- XAU/USD: {fmt_num_us(snap.xauusd)} ({spot_icon_show} "
                    f"{fmt_pct(spot_pct)})",
                    f"- USD/IDR: {fmt_num_us(snap.usdidr)} ({fx_icon_show} "
                    f"{fmt_pct(fx_pct)})",
                    f"- Est. Spot Rp/gram: {fmt_rp(snap.spot_idr_gr)}",
                    "",
                    "Lokal (Logam Mulia)",
                    f"- Antam 1gr (Harga Dasar): {fmt_rp(snap.antam_1g_base)}",
                    f"- Antam 1gr (+PPh 0.25%): {fmt_rp(snap.antam_1g_pph)}",
                    f"- Buyback: {fmt_rp(snap.buyback)}"
                    + (
                        f" ({bb_icon_show} {fmt_rp(buyback_delta)})"
                        if buyback_delta is not None
                        else ""
                    ),
                    "",
                    "Catatan cepat",
                    f"- Spread (Dasar - Buyback): {fmt_rp(spread)}/gr",
                    f"- Timestamp buyback: {snap.buyback_ts or '-'}",
                    "",
                    f"Sumber: Spot via {snap.spot_source} "
                    f"(fallback GoldAPI), Lokal via Logam Mulia.",
                ],
            )
            send_telegram(
                settings.TELEGRAM_BOT_TOKEN,
                settings.TELEGRAM_CHANNEL_ID,
                msg,
                dry_run=settings.DRY_RUN,
            )
            BroadcastLog.objects.create(
                kind=BroadcastLog.KIND_UPDATE,
                slot_key=slot_key,
                message=msg,
            )
        return

    # 3) cek breaking alert
    cond_spot = (spot_pct is not None) and (abs(spot_pct) >= settings.SPOT_ALERT_PCT)
    cond_bb = (buyback_delta is not None) and (
        abs(buyback_delta) >= settings.BUYBACK_ALERT_RP
    )

    if cond_spot or cond_bb:
        last_alert = (
            BroadcastLog.objects.filter(kind=BroadcastLog.KIND_ALERT)
            .order_by("-sent_at")
            .first()
        )
        if can_send(
            last_alert.sent_at if last_alert else None,
            settings.COOLDOWN_ALERT_MIN,
        ):
            direction = "naik" if (spot_pct or 0) >= 0 else "turun"
            note = "Spot bergerak duluan—harga lokal biasanya menyusul bertahap."
            msg = "\n".join(
                [
                    f"🚨 [ALERT EMAS] {direction} cepat",
                    "",
                    f"- XAU/USD: {fmt_num_us(snap.xauusd)} ({spot_icon_show} "
                    f"{fmt_pct(spot_pct)} sejak update terakhir)",
                    f"- Est. Spot Rp/gram: {fmt_rp(snap.spot_idr_gr)}",
                    f"- Buyback LM: {fmt_rp(snap.buyback)}"
                    + (
                        f" ({bb_icon_show} {fmt_rp(buyback_delta)})"
                        if buyback_delta is not None
                        else ""
                    ),
                    "",
                    f"Catatan: {note}",
                    "",
                    f"Sumber: {snap.spot_source} / GoldAPI, Logam Mulia.",
                ],
            )
            send_telegram(
                settings.TELEGRAM_BOT_TOKEN,
                settings.TELEGRAM_CHANNEL_ID,
                msg,
                dry_run=settings.DRY_RUN,
            )
            BroadcastLog.objects.create(kind=BroadcastLog.KIND_ALERT, message=msg)
