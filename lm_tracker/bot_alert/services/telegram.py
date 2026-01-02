import requests


def send_telegram(bot_token: str, chat_id: str, text: str, *, dry_run=False):
    if dry_run:
        return
    r = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout=25,
    )
    r.raise_for_status()
