from __future__ import annotations

from decimal import Decimal

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import Subscription
from .models import TelegramUser
from .models import Transaction


@sync_to_async
def get_or_create_telegram_user(u) -> TelegramUser:
    tg_user_id = u.id
    first_name = u.first_name
    last_name = u.last_name
    username = u.username

    name = f"{first_name} {last_name}".strip()
    telegram_user, _ = TelegramUser.objects.get_or_create(
        telegram_user_id=tg_user_id,
        defaults={"username": username or "", "name": name or ""},
    )
    # update basic fields (best-effort)
    changed = False
    if username is not None and telegram_user.username != (username or ""):
        telegram_user.username = username or ""
        changed = True
    if name is not None and telegram_user.name != (name or ""):
        telegram_user.name = name or ""
        changed = True
    if changed:
        telegram_user.save(update_fields=["username", "name"])
    # ensure subscription row exists
    Subscription.objects.get_or_create(telegram_user=telegram_user)
    return telegram_user


@sync_to_async
def is_pro(telegram_user: TelegramUser) -> bool:
    sub = getattr(telegram_user, "subscription", None)
    return bool(sub and sub.is_pro_active())


@sync_to_async
def free_quota_remaining(telegram_user: TelegramUser) -> int:
    limit = getattr(settings, "FREE_TXN_LIMIT_PER_MONTH", 30)
    now = timezone.now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = Transaction.objects.filter(
        telegram_user=telegram_user,
        created__gte=start,
    ).count()
    return max(0, limit - used)


async def can_add_txn(telegram_user: TelegramUser) -> bool:
    is_telegram_user_pro = await is_pro(telegram_user)
    if is_telegram_user_pro:
        return True
    remaining = await free_quota_remaining(telegram_user)
    return remaining > 0


@sync_to_async
def today_summary(telegram_user: TelegramUser):
    now = timezone.localtime(timezone.now())
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    qs = Transaction.objects.filter(telegram_user=telegram_user, created__gte=start)

    agg = qs.values("side").annotate(total=Sum("total_amount"))
    totals = {row["side"]: int(row["total"] or 0) for row in agg}

    # stok gram (buy +, sell/buyback -). fee tidak ngaruh stok
    stock = {"GOLD": 0, "SILVER": 0}
    txs = qs.exclude(weight_gram__isnull=True).only(
        "asset",
        "side",
        "weight_gram",
        "pcs",
    )
    for t in txs:
        grams = float(t.weight_gram) * int(t.pcs)
        if t.side in (Transaction.SIDE_BUY, Transaction.SIDE_BUYBACK):
            stock[f"{t.asset}"] += grams
        elif t.side == Transaction.SIDE_SELL:
            stock[f"{t.asset}"] -= grams

    return totals, stock


@sync_to_async
def stock_all_time(telegram_user: TelegramUser):
    stock = {"GOLD": 0, "SILVER": 0}
    txs = (
        Transaction.objects.filter(telegram_user=telegram_user)
        .exclude(weight_gram__isnull=True)
        .only("asset", "side", "weight_gram", "pcs")
    )
    for t in txs:
        grams = float(t.weight_gram) * int(t.pcs)
        if t.side == Transaction.SIDE_BUY:
            stock[f"{t.asset}"] += grams
        elif t.side in (Transaction.SIDE_SELL, Transaction.SIDE_BUYBACK):
            stock[f"{t.asset}"] -= grams
    return stock


@sync_to_async
@transaction.atomic
def create_tx_from_text(telegram_user: TelegramUser, asset, parsed, update):
    return Transaction.objects.create(
        telegram_user=telegram_user,
        asset=asset,
        product=parsed.product,
        side=parsed.side,
        weight_gram=parsed.weight_gram,
        pcs=parsed.pcs,
        total_amount=parsed.total_amount,
        note=parsed.note,
        chat_id=update.effective_chat.id if update.effective_chat else None,
        message_id=update.message.message_id,
    )


@sync_to_async
def delete_tx_by_telegram_user_and_id(
    telegram_user: TelegramUser,
    tx_id: int,
) -> Transaction | None:
    tx = Transaction.objects.filter(telegram_user=telegram_user, id=tx_id).first()
    if not tx:
        return None
    tx.delete()
    return tx


@sync_to_async
def delete_last_tx(telegram_user: TelegramUser) -> int | None:
    tx = (
        Transaction.objects.filter(telegram_user=telegram_user)
        .order_by("-tx_date", "-id")
        .first()
    )
    tid = tx.id
    if not tx:
        return None
    tx.delete()
    return tid


@sync_to_async
def summary_simple(telegram_user: TelegramUser) -> dict:
    """
    MVP summary (simple):
      - total_buy_grams, total_sell_grams (sell+buyback)
      - holdings_grams (buy - sell - buyback)
      - avg_buy_price (berdasarkan transaksi BUY saja)
    """

    txs = Transaction.objects.filter(telegram_user=telegram_user).order_by(
        "-tx_date",
        "-id",
    )

    buys = txs.filter(side="BUY")
    sells = txs.filter(side="SELL")
    buybacks = txs.filter(side="BUYBACK")

    # total buys
    total_buy_grams = Decimal("0")
    for tx in buys.only("weight_gram", "pcs"):
        total_buy_grams += Decimal(tx.weight_gram or "0") * Decimal(tx.pcs or "1")

    # total sells
    total_sell_grams = Decimal("0")
    for tx in sells.only("weight_gram", "pcs"):
        total_sell_grams += Decimal(tx.weight_gram or "0") * Decimal(tx.pcs or "1")

    # total buybacks
    total_buyback_grams = Decimal("0")
    for tx in buybacks.only("weight_gram", "pcs"):
        total_buyback_grams += Decimal(tx.weight_gram or "0") * Decimal(tx.pcs or "1")

    # avg buy price (simple)
    total_buy_cost = Decimal("0")
    for tx in buys.only("total_amount"):
        total_buy_cost += Decimal(tx.total_amount)

    holdings = (total_buy_grams + total_buyback_grams) - total_sell_grams
    avg_buy = (total_buy_cost / total_buy_grams) if total_buy_grams > 0 else None

    return {
        "exists": True,
        "total_buy_grams": total_buy_grams,
        "total_sell_grams": total_sell_grams,
        "holdings": holdings,
        "avg_buy": avg_buy,
        "last_tx_date": (txs.first().tx_date if txs.exists() else None),
    }


@sync_to_async
def list_last_txs(
    telegram_user: TelegramUser,
    limit: int = 5,
    metal_type: str | None = None,
):
    qs = Transaction.objects.filter(telegram_user=telegram_user).order_by(
        "-tx_date",
        "-id",
    )
    if metal_type in ("GOLD", "SILVER"):
        qs = qs.filter(asset=metal_type)

    return list(qs[:limit])
