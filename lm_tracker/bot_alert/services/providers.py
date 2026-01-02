import re

import cloudscraper
import requests
from bs4 import BeautifulSoup
from twelvedata import TDClient

PRICE_URL = "https://www.logammulia.com/harga-emas-hari-ini"
PRICE_URLS = [
    "https://www.logammulia.com/harga-emas-hari-ini",
    "https://www.logammulia.com/id/harga-emas-hari-ini",
    "https://www.logammulia.com/en/harga-emas-hari-ini",
]
BUYBACK_URL = "https://www.logammulia.com/id/sell/gold"
BUYBACK_URLS = [
    "https://www.logammulia.com/id/sell/gold",
]
THREE_LEN = 3


def is_cf_challenge(html: str) -> bool:
    return (
        ("Just a moment" in html)
        or ("_cf_chl_opt" in html)
        or ("/cdn-cgi/challenge-platform" in html)
    )


def td_latest_close(api_key: str, symbol: str, interval="1min") -> float:
    try:
        td = TDClient(apikey=api_key)
        ts = td.time_series(
            symbol=symbol,
            interval=interval,
            outputsize=1,
            timezone="Asia/Jakarta",
        )
        data = ts.as_json()
        return float(data[0]["close"])
    except Exception as err:
        msg = f"TwelveData error: {err}"
        raise RuntimeError(msg) from err


def goldapi_xauusd(api_key: str, symbol: str, curr: str) -> float:
    date = ""
    url = f"https://www.goldapi.io/api/{symbol}/{curr}{date}"
    headers = {
        "x-access-token": api_key,
        "Content-Type": "application/json",
    }
    r = requests.get(url, headers=headers, timeout=35)
    r.raise_for_status()
    return float(r.json()["price"])


def get_spot_world(td_key: str, gold_key: str):
    try:
        xauusd = td_latest_close(td_key, "XAU/USD")
        usdidr = td_latest_close(td_key, "USD/IDR")
    except RuntimeError:
        xauusd = goldapi_xauusd(gold_key, "XAU", "USD")
        usdidr = td_latest_close(td_key, "USD/IDR")
        return xauusd, usdidr, "GoldAPI+TwelveData"
    else:
        return xauusd, usdidr, "TwelveData"


def calc_spot_idr_per_gram(xauusd: float, usdidr: float) -> float:
    return (xauusd * usdidr) / 31.1034768


def rupiah_to_int(s: str) -> int:
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else 0


def fetch_antam_1g_prices():
    th_title = "Emas Batangan"
    scraper = cloudscraper.create_scraper(interpreter="nodejs")
    html = scraper.get(PRICE_URL).text
    soup = BeautifulSoup(html, "html.parser")

    # OPTIONAL: buang swal overlay kalau ada (tidak wajib)
    for sel in [".swal-overlay", ".swal-modal", ".swal-overlay--show-modal"]:
        for node in soup.select(sel):
            node.decompose()

    # cari <th> yang text-nya "Emas Batangan"
    th = soup.find("th", string=lambda x: x and x.strip() == th_title)
    if not th:
        msg = f"<th>{th_title}</th> tidak ditemukan"
        raise RuntimeError(msg)

    table = th.find_parent("table")
    if not table:
        msg = "Table parent dari <th> tidak ditemukan"
        raise RuntimeError(msg)

    header_tr = th.find_parent("tr")

    # iterasi row setelah header "Emas Batangan"
    for tr in header_tr.find_all_next("tr"):
        # stop kalau ketemu header section lain (tr yang punya <th>)
        th2 = tr.find("th")
        if th2 and th2.get_text(strip=True) != th_title:
            break

        tds = tr.find_all("td")
        if len(tds) < THREE_LEN:
            continue

        cells = [td.get_text(" ", strip=True) for td in tds]
        berat = cells[0].lower()
        if berat == "1 gr":
            base = rupiah_to_int(cells[1])
            pph = rupiah_to_int(cells[2])
            if base and pph:
                return base, pph

    msg = "Gagal parse Antam 1gr"
    raise RuntimeError(msg)


def fetch_buyback():
    scraper = cloudscraper.create_scraper(interpreter="nodejs")
    html = scraper.get(BUYBACK_URL).text
    text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)

    m_price = re.search(r"Harga\s*Buyback\s*:\s*Rp\s*([\d\.\,]+)", text, re.IGNORECASE)
    if not m_price:
        msg = "Gagal parse buyback"
        raise RuntimeError(msg)

    buyback = rupiah_to_int(m_price.group(1))
    m_ts = re.search(r"Perubahan\s*Terakhir\s*:\s*(.+)", text, re.IGNORECASE)
    ts = m_ts.group(1).strip() if m_ts else None
    return buyback, ts
