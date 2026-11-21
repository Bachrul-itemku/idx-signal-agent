import requests
import config

LIMIT = 3900   # batas Telegram 4096 karakter, sisakan ruang


def _chunks(text: str):
    """Potong per blok (baris kosong) supaya tag HTML tidak terbelah."""
    buf = ""
    for block in text.split("\n\n"):
        piece = block if not buf else "\n\n" + block
        if len(buf) + len(piece) > LIMIT and buf:
            yield buf
            buf = block
        else:
            buf += piece
    if buf:
        yield buf


def send(text: str) -> None:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("[telegram] token/chat_id kosong, cetak saja:\n" + text)
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    for part in _chunks(text):
        r = requests.post(url, data={
            "chat_id": config.TELEGRAM_CHAT_ID, "text": part,
            "parse_mode": "HTML", "disable_web_page_preview": True,
        }, timeout=20)
        if not r.ok:
            print(f"[telegram] error {r.status_code}: {r.text}")
