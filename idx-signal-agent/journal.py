"""Jurnal sinyal (SQLite): simpan tiap sinyal, evaluasi hasilnya, hitung winrate.

Asumsi evaluasi (sengaja konservatif):
- Entry = harga close hari sinyal.
- Hari-hari berikutnya: kalau low <= SL -> LOSS di SL; kalau high >= TP1 -> WIN di TP1.
  Kalau SL dan TP1 tersentuh di hari yang sama, dianggap LOSS (tidak tahu mana duluan).
- Lewat MAX_HOLD hari bursa tanpa kena keduanya -> EXPIRED di harga close.
- Peringatan exit dinilai BENAR kalau close 5 hari bursa kemudian lebih rendah.
- BPJS (mode next_day): entry = open besok; WIN kalau high besok >= open +2,5%,
  selain itu dijual di close besok (untung/rugi sesuai close).
"""
import sqlite3
from datetime import datetime
import pandas as pd
import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tanggal TEXT, kode TEXT, tipe TEXT,
    close REAL, entry REAL, sl REAL, tp1 REAL, rr REAL,
    rsi REAL, vol_ratio REAL, skor INTEGER, mode TEXT,
    ai_pick INTEGER,            -- 1 dipilih AI, 0 dibuang AI, NULL tanpa AI
    ai_komentar TEXT,
    status TEXT DEFAULT 'OPEN', -- OPEN / WIN / LOSS / EXPIRED / BENAR / SALAH
    exit_date TEXT, exit_price REAL, result_pct REAL, hold_days INTEGER,
    created_at TEXT,
    UNIQUE(tanggal, kode, tipe)
)"""


def conn():
    c = sqlite3.connect(config.DB_PATH)
    c.execute(SCHEMA)
    cols = {r[1] for r in c.execute("PRAGMA table_info(signals)")}
    for col, typ in [("skor", "INTEGER"), ("mode", "TEXT")]:   # migrasi DB versi lama
        if col not in cols:
            c.execute(f"ALTER TABLE signals ADD COLUMN {col} {typ}")
    return c


def save(info: dict, ai_pick: int | None, komentar: str = "") -> None:
    s = info["signal"]
    with conn() as c:
        c.execute("""INSERT OR IGNORE INTO signals
            (tanggal,kode,tipe,close,entry,sl,tp1,rr,rsi,vol_ratio,skor,mode,ai_pick,ai_komentar,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (info["tanggal"], info["kode"], s["tipe"], info["close"], s.get("entry"),
             s.get("sl"), s.get("tp1"), s.get("rr"), info["rsi"], info["vol_ratio"],
             s.get("skor"), s.get("mode", "swing"),
             ai_pick, komentar, datetime.now().isoformat(timespec="seconds")))


def _evaluate(row: dict, df: pd.DataFrame) -> dict | None:
    after = df[df.index > pd.Timestamp(row["tanggal"])]
    if after.empty:
        return None

    mode = row.get("mode") or ("warning" if row["tipe"] in ("VAL_BREAKDOWN", "EXIT_WARNING") else "swing")

    if mode == "next_day":
        bar = after.iloc[0]
        o = float(bar["Open"])
        if bar["High"] >= o * 1.025:
            px, status = o * 1.025, "WIN"
        else:
            px = float(bar["Close"])
            status = "WIN" if px > o else "LOSS"
        return {"status": status, "exit_date": str(after.index[0].date()), "exit_price": px,
                "result_pct": round((px / o - 1) * 100, 2), "hold_days": 1}

    if mode == "warning":
        if len(after) < 5:
            return None
        px = float(after["Close"].iloc[4])
        chg = (px / row["close"] - 1) * 100
        return {"status": "BENAR" if chg < 0 else "SALAH", "exit_date": str(after.index[4].date()),
                "exit_price": px, "result_pct": round(chg, 2), "hold_days": 5}

    for i, (ts, bar) in enumerate(after.iterrows(), start=1):
        hit_sl = bar["Low"] <= row["sl"]
        hit_tp = bar["High"] >= row["tp1"]
        if hit_sl or hit_tp:
            px = row["sl"] if hit_sl else row["tp1"]
            return {"status": "LOSS" if hit_sl else "WIN", "exit_date": str(ts.date()),
                    "exit_price": px, "result_pct": round((px / row["entry"] - 1) * 100, 2),
                    "hold_days": i}
        if i >= config.MAX_HOLD_DAYS:
            px = float(bar["Close"])
            return {"status": "EXPIRED", "exit_date": str(ts.date()), "exit_price": px,
                    "result_pct": round((px / row["entry"] - 1) * 100, 2), "hold_days": i}
    return None


def update_open(get_df) -> int:
    """get_df(kode) -> DataFrame harian. Return jumlah sinyal yang ditutup."""
    closed = 0
    with conn() as c:
        c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute("SELECT * FROM signals WHERE status='OPEN'")]
        for row in rows:
            df = get_df(row["kode"])
            if df is None:
                continue
            res = _evaluate(row, df)
            if res:
                c.execute("""UPDATE signals SET status=?, exit_date=?, exit_price=?,
                             result_pct=?, hold_days=? WHERE id=?""",
                          (res["status"], res["exit_date"], res["exit_price"],
                           res["result_pct"], res["hold_days"], row["id"]))
                closed += 1
    return closed


def stats() -> dict:
    with conn() as c:
        df = pd.read_sql("SELECT * FROM signals", c)
    out = {"total": len(df), "open": int((df["status"] == "OPEN").sum()) if len(df) else 0,
           "per_tipe": [], "ai": []}
    if df.empty:
        return out

    trades = df[df["status"].isin(["WIN", "LOSS", "EXPIRED"])]
    for tipe, g in trades.groupby("tipe"):
        out["per_tipe"].append(_summary(tipe, g))

    warn = df[df["status"].isin(["BENAR", "SALAH"])]
    if len(warn):
        out["breakdown"] = {"n": len(warn), "akurasi": round((warn["status"] == "BENAR").mean() * 100, 1)}

    # Apakah filter AI membantu? Bandingkan yang dipilih vs dibuang AI.
    for flag, name in [(1, "Dipilih AI"), (0, "Dibuang AI")]:
        g = trades[trades["ai_pick"] == flag]
        if len(g):
            out["ai"].append(_summary(name, g))
    return out


def _summary(name, g):
    wins, losses = g[g["result_pct"] > 0], g[g["result_pct"] <= 0]
    avg_w = wins["result_pct"].mean() if len(wins) else 0
    avg_l = losses["result_pct"].mean() if len(losses) else 0
    return {"nama": name, "n": len(g),
            "winrate": round(len(wins) / len(g) * 100, 1),
            "avg_win": round(avg_w, 2), "avg_loss": round(avg_l, 2),
            "expectancy": round(g["result_pct"].mean(), 2)}


def stats_text() -> str:
    s = stats()
    lines = ["📈 <b>Rapor Sinyal</b>",
             f"Total tercatat {s['total']} · masih berjalan {s['open']}"]
    if not s["per_tipe"] and "breakdown" not in s:
        lines.append("\nBelum ada sinyal yang selesai dievaluasi.")
        return "\n".join(lines)

    def row(x):
        return (f"• <b>{x['nama']}</b>: {x['n']} trade · winrate {x['winrate']}% · "
                f"avg win {x['avg_win']:+}% · avg loss {x['avg_loss']:+}% · "
                f"rata-rata/trade {x['expectancy']:+}%")

    if s["per_tipe"]:
        lines.append("\n<b>Per jenis sinyal</b>")
        lines += [row(x) for x in s["per_tipe"]]
    if "breakdown" in s:
        b = s["breakdown"]
        lines.append(f"• <b>Peringatan exit</b>: {b['n']} sinyal · akurasi {b['akurasi']}%")
    if s["ai"]:
        lines.append("\n<b>Efek filter AI</b>")
        lines += [row(x) for x in s["ai"]]
    lines.append("\n<i>Asumsi: swing entry di close hari sinyal, SL/TP di level persis, "
                 f"maks {config.MAX_HOLD_DAYS} hari bursa; BPJS entry di open besok. "
                 "Belum termasuk fee & slippage.</i>")
    return "\n".join(lines)
