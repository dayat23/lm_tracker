from __future__ import annotations

import csv
import io
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram import Update

from django.conf import settings
from django.utils import timezone
from telegram.ext import Application
from telegram.ext import ApplicationBuilder
from telegram.ext import CommandHandler
from telegram.ext import ContextTypes
from telegram.ext import MessageHandler
from telegram.ext import filters

from .models import ActivationToken
from .models import Subscription
from .models import Transaction
from .parser import parse_transaction
from .services import can_add_txn
from .services import create_tx_from_text
from .services import delete_last_tx
from .services import delete_tx_by_telegram_user_and_id
from .services import get_or_create_telegram_user
from .services import list_last_txs
from .services import stock_all_time
from .services import summary_simple
from .services import today_summary

TWO_LEN = 2


def build_app() -> Application:
    app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("upgrade", cmd_upgrade))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("stock", cmd_stock))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("list", cmd_list))

    # parse plain text messages as potential transactions
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_text))

    return app


def _fmt_int(n: int) -> str:
    return f"{int(n):,}".replace(",", ".")


def _fmt_rp(n: int) -> str:
    return "Rp " + _fmt_int(n)


def _fmt_gr(d: Decimal) -> str:
    # tampil 3 desimal, hapus trailing nol
    s = f"{d:.1f}"
    return s.rstrip("0").rstrip(".")


def _parse_metal_arg(arg: str) -> str | None:
    a = (arg or "").strip().lower()
    if a in ("emas", "gold", "xau"):
        return "GOLD"
    if a in ("perak", "silver", "xag"):
        return "SILVER"
    return None


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not u:
        return
    telegram_user = await get_or_create_telegram_user(u)

    # Activation deep link: /start paid_<token>
    if update.message and update.message.text:
        parts = update.message.text.split(maxsplit=1)
        if len(parts) == TWO_LEN and parts[1].startswith("paid_"):
            token = parts[1].replace("paid_", "", 1).strip()
            ok = await _consume_activation_token(telegram_user, token)
            if ok:
                await update.message.reply_text(
                    "✅ PRO aktif. Terima kasih! Coba: /export atau /stock",
                )
            else:
                await update.message.reply_text(
                    "Token aktivasi tidak valid / sudah dipakai.",
                )
            return

    await update.message.reply_text(
        "Halo! Saya bot pencatatan transaksi EMAS/PERAK.\n\n"
        "Kirim transaksi seperti:\n"
        "- jual emas ANTAM 2gr 2pcs total 11.000.000\n"
        "- beli perak ANTAM 100gr total 1.250.000\n"
        "- bb emas ANTAM 100gr total 1.250.000\n\n"
        "Cek laporan: /today /stock /summary /export\n"
        "Upgrade: /upgrade",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Cara catat:\n"
        "- beli emas ANTAM 2gr 2pcs total 11.000.000\n"
        "- jual emas 1gr total 1.200.000\n"
        "- buyback emas 5gr total 28.000.000\n\n"
        "Laporan:\n"
        "- /today\n- /stock\n- /summary\n- /export (PRO)\n\n"
        "Manajemen:\n"
        "- /delete last\n- /delete <id>\n\n"
        "Upgrade:\n- /upgrade",
    )


async def cmd_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not u:
        return
    telegram_user = await get_or_create_telegram_user(u)
    # simple checkout link
    # (Django view will generate activation token after payment simulated)
    link = (
        f"{settings.APP_BASE_URL}/billing/checkout/?tg={telegram_user.telegram_user_id}"
    )
    await update.message.reply_text(
        "Upgrade ke PRO:\n"
        "✅ Unlimited transaksi\n"
        "✅ Export CSV\n"
        "✅ Fitur baru\n\n"
        f"Klik untuk bayar: {link}\n"
        "Setelah bayar, kamu akan diarahkan untuk aktivasi otomatis.",
    )


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not u:
        return
    telegram_user = await get_or_create_telegram_user(u)
    totals, stock = await today_summary(telegram_user)
    buy = totals.get("BUY", 0)
    sell = totals.get("SELL", 0)
    buyback = totals.get("BUYBACK", 0)
    net = (sell - buy) - buyback

    await update.message.reply_text(
        f"📄 Rekap Hari Ini:\n"
        f"- BUY: {_fmt_rp(buy)}\n"
        f"- SELL: {_fmt_rp(sell)}\n"
        f"- BUYBACK: {_fmt_rp(buyback)}\n\n"
        f"📌 Net Cashflow: {_fmt_rp(net)}\n"
        f"📌 Stok hari ini:\n"
        f"- EMAS: {_fmt_gr(stock['GOLD'])} gr\n"
        f"- PERAK: {_fmt_gr(stock['SILVER'])} gr",
    )


async def cmd_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not u:
        return
    telegram_user = await get_or_create_telegram_user(u)
    stock = await stock_all_time(telegram_user)
    await update.message.reply_text(
        "📌 Stok Saat Ini:\n"
        f"- EMAS: {stock['GOLD']:.1f} gr\n"
        f"- PERAK: {stock['SILVER']:.1f} gr",
    )


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not u:
        return
    telegram_user = await get_or_create_telegram_user(u)

    if not telegram_user.subscription.is_pro_active():
        await update.message.reply_text("Fitur /export hanya untuk PRO. Ketik /upgrade")
        return

    # default: export bulan ini
    now = timezone.localtime(timezone.now())
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    txs = Transaction.objects.filter(
        telegram_user=telegram_user,
        created_at__gte=start,
    ).order_by("created_at")

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "created_at",
            "side",
            "asset",
            "product",
            "weight_gram",
            "pcs",
            "total_amount",
            "note",
        ],
    )
    for t in txs:
        writer.writerow(
            [
                t.id,
                timezone.localtime(t.created_at).isoformat(),
                t.side,
                t.asset,
                t.product,
                str(t.weight_gram or ""),
                t.pcs,
                t.total_amount,
                t.note,
            ],
        )

    data = buf.getvalue().encode("utf-8")
    filename = f"transactions_{now.strftime('%Y_%m')}.csv"

    await update.message.reply_document(
        document=data,
        filename=filename,
        caption="✅ Export CSV bulan ini",
    )


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not u or not update.message:
        return
    telegram_user = await get_or_create_telegram_user(u)

    args = update.message.text.split()
    if len(args) < TWO_LEN:
        await update.message.reply_text("Pakai: /delete last atau /delete <id>")
        return

    target = args[1].strip().lower()
    if target == "last":
        tid = await delete_last_tx(telegram_user)
        if not tid:
            await update.message.reply_text("Belum ada transaksi.")
            return
        await update.message.reply_text(f"🗑️ Dihapus transaksi terakhir (#{tid})")
        return

    if target.isdigit():
        tid = int(target)
        tx = await delete_tx_by_telegram_user_and_id(telegram_user, tid)
        if not tx:
            await update.message.reply_text("ID tidak ditemukan.")
            return
        await update.message.reply_text(f"🗑️ Dihapus transaksi #{tid}")
        return
    await update.message.reply_text("Pakai: /delete last atau /delete <id>")


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not u or not update.message:
        return

    telegram_user = await get_or_create_telegram_user(u)
    s = await summary_simple(telegram_user)
    if not s.get("exists"):
        await update.message.reply_text(
            "Belum ada portfolio. Kirim transaksi pertama dulu ya.",
        )
        return

    avg_buy = s["avg_buy"]
    avg_buy_str = _fmt_rp(int(avg_buy)) if avg_buy is not None else "-"
    await update.message.reply_text(
        "\n".join(
            [
                "📊 Ringkasan (simple):",
                f"- Total masuk (beli + buyback): {_fmt_gr(s['total_buy_grams'])}gr",
                f"- Total jual: {_fmt_gr(s['total_sell_grams'])}gr",
                f"- Holdings: {_fmt_gr(s['holdings'])}gr",
                f"- Avg beli (BUY saja): {avg_buy_str}/gr",
                "",
                "Catatan: ringkasan ini versi MVP (belum FIFO/realized P&L).",
            ],
        ),
    )


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not u or not update.message:
        return

    telegram_user = await get_or_create_telegram_user(u)

    metal_type = None
    limit = 5

    for arg in context.args or []:
        m = _parse_metal_arg(arg)
        if m:
            metal_type = m
            continue
        if arg.isdigit():
            limit = max(1, min(int(arg), 50))
            continue

    txs = await list_last_txs(telegram_user, limit=limit, metal_type=metal_type)
    scope = (
        "EMAS"
        if metal_type == "GOLD"
        else ("PERAK" if metal_type == "SILVER" else "SEMUA")
    )
    if not txs:
        await update.message.reply_text(f"Belum ada transaksi ({scope}).")
        return

    lines = [f"📄 {len(txs)} transaksi terakhir ({scope}):"]

    total_pcs = 0
    total_amount_sum = 0
    total_grams_sum = 0  # tampil sederhana (float) untuk total list

    for tx in txs:
        metal_label = "EMAS" if tx.asset == "GOLD" else "PERAK"
        pcs = tx.pcs or 1
        total_pcs += pcs

        total_amount = tx.total_amount
        total_amount_sum += int(total_amount)

        # grams sum (Decimal -> float untuk display ringkas)
        total_grams_sum += float(tx.total_weight)

        # Breakdown pcs x gram/pcs
        per_piece = None
        if pcs > 0:
            per_piece = tx.weight_gram

        breakdown = f"{pcs}pcs"
        if per_piece is not None:
            breakdown += f" x {_fmt_gr(per_piece)}gr"

        price_per_gram = tx.total_amount / tx.pcs

        lines.append(
            f"- {tx.side} | {metal_label} {tx.product} "
            f"{_fmt_gr(tx.weight_gram)}gr | {breakdown} | "
            f"@ {_fmt_rp(price_per_gram)}/gr | total {_fmt_rp(total_amount)}"
            f" | {tx.tx_date}",
        )

    lines.append("")
    lines.append("📌 Total (dari list ini):")
    lines.append(f"- Total pcs: {total_pcs}pcs")
    lines.append(
        f"- Total gram: {_fmt_gr(Decimal(total_grams_sum))}gr".rstrip("0").rstrip("."),
    )
    lines.append(f"- Total nilai: {_fmt_rp(total_amount_sum)}")

    await update.message.reply_text("\n".join(lines))


async def msg_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    u = update.effective_user
    telegram_user = await get_or_create_telegram_user(u)

    parsed = parse_transaction(update.message.text)
    if not parsed:
        # ignore non-transaction chat
        return

    is_can_add_txn = await can_add_txn(telegram_user)
    if not is_can_add_txn:
        await update.message.reply_text(
            "Kuota FREE kamu sudah habis.\n"
            "Upgrade untuk lanjut catat + export.\n"
            "Ketik /upgrade",
        )
        return

    asset = parsed.asset or Transaction.ASSET_GOLD

    t = await create_tx_from_text(telegram_user, asset, parsed, update)

    # reply summary
    total_weight = ""
    if t.weight_gram is not None:
        tw = Decimal(t.weight_gram) * int(t.pcs)
        total_weight = (
            f"\nBerat: {_fmt_gr(t.weight_gram)} gr X {t.pcs} pcs ({_fmt_gr(tw)} gr)"
        )

    product = f"{t.product} " if t.product else ""
    await update.message.reply_text(
        f"✅ Tercatat: {t.side} {product}{t.asset}"
        f"{total_weight}\n"
        f"Total: {_fmt_rp(t.total_amount)}\n"
        f"ID: #{t.id}",
    )


async def _consume_activation_token(telegram_user, token: str) -> bool:
    try:
        at = ActivationToken.objects.get(token=token)
    except ActivationToken.DoesNotExist:
        return False
    if not at.is_valid():
        return False

    sub = telegram_user.subscription
    sub.plan = Subscription.PLAN_PRO
    sub.status = Subscription.STATUS_ACTIVE
    sub.current_period_end = timezone.now() + timedelta(days=30)
    sub.save(update_fields=["plan", "status", "current_period_end"])

    at.used_at = timezone.now()
    at.save(update_fields=["used_at"])
    return True
