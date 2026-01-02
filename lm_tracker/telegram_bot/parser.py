from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

FOUR_LEN = 4


@dataclass
class ParsedTxn:
    side: str
    asset: str | None
    product: str
    weight_gram: Decimal | None
    pcs: int
    total_amount: int
    note: str


SIDE_MAP = {
    "beli": "BUY",
    "buy": "BUY",
    "jual": "SELL",
    "sell": "SELL",
    "buyback": "BUYBACK",
    "bb": "BUYBACK",
    "fee": "FEE",
    "biaya": "FEE",
    "ongkir": "FEE",
}

ASSET_HINT_EMAS = {"emas", "gold"}
ASSET_HINT_PERAK = {"perak", "silver"}

STOP_WORDS = {
    "emas",
    "perak",
    "total",
    "rp",
    "gr",
    "gram",
    "pcs",
    "pc",
    "keping",
    "note",
    "catatan",
    "buyback",
    "bb",
    "beli",
    "jual",
    "buy",
    "sell",
    "fee",
    "biaya",
    "ongkir",
}


def _is_word(tok: str) -> bool:
    return re.fullmatch(r"[A-Za-z]+", tok) is not None


def _is_number(tok: str) -> bool:
    return re.fullmatch(r"\d+", tok) is not None


def _is_alnum_brand(tok: str) -> bool:
    # kalau ada brand model "GALERI24" atau "ABC123"
    return re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", tok) is not None


def _norm_amount(s: str) -> int:
    s = s.lower().replace("rp", "").replace(" ", "")
    s = s.replace(".", "")
    s = s.replace(",", "")  # kalau user pakai koma sebagai ribuan
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else 0


def _note_raw_text(raw: str) -> tuple[str, str, str]:
    lower = raw.lower()
    m_note = re.search(
        r"(note|catatan|penjual|pembeli)\s*[:=]\s*(.+)$",
        raw,
        flags=re.IGNORECASE,
    )
    note = ""

    if m_note:
        note = m_note.group(2).strip()
        raw_wo_note = raw[: m_note.start()].strip()
        lower_wo_note = raw_wo_note.lower()
    else:
        raw_wo_note = raw
        lower_wo_note = lower
    return note, raw_wo_note, lower_wo_note


def parse_transaction(text: str) -> ParsedTxn | None:
    raw = (text or "").strip()
    if not raw:
        return None

    # NOTE
    note, raw_wo_note, lower_wo_note = _note_raw_text(raw)

    # SIDE
    first_word = lower_wo_note.split()[0] if lower_wo_note.split() else ""
    side = SIDE_MAP.get(first_word)
    if not side:
        # fallback: cari keyword di kalimat
        for k, v in SIDE_MAP.items():
            if re.search(rf"\b{k}\b", lower_wo_note):
                side = v
                break
    if not side:
        return None

    # ASSET
    asset = None
    tokens = set(re.findall(r"[a-zA-Z]+", lower_wo_note))
    if tokens & ASSET_HINT_EMAS:
        asset = "GOLD"
    if tokens & ASSET_HINT_PERAK:
        asset = "SILVER"

    # WEIGHT
    weight_gram = None
    m_w = re.search(r"(\d+(?:[.,]\d+)?)\s*(gr|gram)\b", lower_wo_note)
    if m_w:
        w = m_w.group(1).replace(",", ".")
        try:
            weight_gram = Decimal(w)
        except ValueError:
            weight_gram = None

    # PCS
    pcs = 1
    m_p = re.search(r"(\d+)\s*(pcs|pc|keping)\b", lower_wo_note)
    if m_p:
        pcs = int(m_p.group(1))

    # TOTAL
    total_amount = 0
    m_t = re.search(r"total\s*[:=]?\s*(rp\s*)?([\d.,]+)", lower_wo_note)
    if m_t:
        total_amount = _norm_amount(m_t.group(2))
    else:
        # fallback: ambil angka terbesar
        nums = re.findall(r"[\d][\d.,]+", lower_wo_note)
        if nums:
            total_amount = max(_norm_amount(x) for x in nums)

    if total_amount <= 0:
        return None

    # PRODUCT (opsional) - support 1-2 token, termasuk "GALERI 24"
    product = ""
    parts = raw_wo_note.split()

    # scan setelah SIDE (kata pertama)
    i = 1
    while i < len(parts):
        tok = parts[i].strip()
        t = tok.lower()

        # stop conditions: kalau sudah masuk angka berat/pcs/total/note,
        # kita berhenti cari product
        if t in {"total", "note", "catatan"}:
            break
        if re.search(r"\d", t) and (
            "gr" in t or "gram" in t or "pcs" in t or "pc" in t
        ):
            break

        # skip stopwords / token berisi angka yang bukan brand
        if t in STOP_WORDS:
            i += 1
            continue

        # kandidat product token pertama
        if _is_word(tok) or _is_alnum_brand(tok):
            # coba gabung 2 token:
            # 1) "GALERI" + "24"
            # 2) "KING" + "GOLD"
            p1 = tok.upper()

            if i + 1 < len(parts):
                tok2 = parts[i + 1].strip()
                t2 = tok2.lower()

                # kalau token kedua adalah angka (untuk GALERI 24)
                if _is_number(tok2) and len(tok2) <= FOUR_LEN:
                    product = f"{p1} {tok2}"
                    break

                # kalau token kedua adalah kata (untuk KING GOLD)
                if _is_word(tok2) and t2 not in STOP_WORDS:
                    product = f"{p1} {tok2.upper()}"
                    break

            # fallback 1 token
            product = p1
            break

        i += 1

    return ParsedTxn(
        side=side,
        asset=asset,
        product=product,
        weight_gram=weight_gram,
        pcs=pcs,
        total_amount=total_amount,
        note=note,
    )
