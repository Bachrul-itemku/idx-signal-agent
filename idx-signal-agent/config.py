import os

try:  # baca file .env kalau ada
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ALL = pindai semua saham IDX (tickers.txt), WATCHLIST = hanya saham di WATCHLIST
UNIVERSE = (os.getenv("UNIVERSE") or "ALL").upper()

# WATCHLIST = saham yang sedang dipegang/dipantau. Dipakai untuk peringatan exit,
# dan ikut dipindai walau belum ada di tickers.txt (mis. saham IPO baru).
# (pakai "or" supaya variabel kosong dari GitHub Actions tetap jatuh ke default)
WATCHLIST = [k.strip() for k in (os.getenv("WATCHLIST") or
    "BBCA,BBRI,BMRI,BBNI,TLKM,ASII,ADRO,ANTM,MDKA,ICBP,UNVR,GOTO,PGAS,PTBA,INCO,AMRT,CPIN,KLBF,SMGR,UNTR"
).split(",") if k.strip()]

VP_LOOKBACK = 120            # candle untuk Volume Profile (~6 bulan)
HISTORY_PERIOD = "2y"        # data yang diunduh (butuh ≥1 tahun untuk low 52 minggu)
MIN_VALUE_MILIAR = 1.0       # rata-rata nilai transaksi 20 hari minimal
BREAKOUT_VOL_RATIO = 1.5     # volume >= 1,5x MA20 untuk breakout
MIN_RR = 1.5                 # risk:reward minimal
MAX_SIGNALS = 10             # maksimal sinyal swing yang dikirim per hari
MAX_PER_LIST = 10            # maksimal saham di daftar BSJP / BPJS
MAX_AI_CANDIDATES = 40       # kandidat terbaik yang ditinjau AI (hemat biaya)
MIN_PRICE = 51               # abaikan saham gocap (harga 50)

# Money management (seperti /MM di bot): lot dihitung dari modal & risiko per trade
MODAL_RP = float(os.getenv("MODAL_RP") or "10000000")   # 10 juta
RISK_PCT = float(os.getenv("RISK_PCT") or "2")          # 2% per trade

DB_PATH = os.getenv("DB_PATH", "signals.db")
MAX_HOLD_DAYS = 20           # sinyal dianggap kedaluwarsa setelah 20 hari bursa

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
USE_AI = os.getenv("USE_AI", "1") == "1"
# 1 = jangan kirim apa-apa kalau data terbaru bukan hari ini (hari libur bursa)
SKIP_STALE = os.getenv("SKIP_STALE", "0") == "1"   # 0 = kirim sinyal mentah tanpa AI
