"""Jurnal sinyal (SQLite): simpan tiap sinyal, evaluasi hasilnya, hitung winrate.

Asumsi evaluasi (sengaja konservatif):
- Entry = harga close hari sinyal.
- Hari-hari berikutnya: kalau low <= SL -> LOSS di SL; kalau high >= TP1 -> WIN di TP1.
  Kalau SL dan TP1 tersentuh di hari yang sama, dianggap LOSS (tidak tahu mana duluan).
- Lewat MAX_HOLD hari bursa tanpa kena keduanya -> EXPIRED di harga close.
- Peringatan exit dinilai BENAR kalau close 5 hari bursa kemudian lebih rendah.
- BPJS: hanya dihitung kalau open besok di antara close dan close+3% (SKIP kalau tidak).
  Entry = open; LOSS kalau low <= close-2%; WIN kalau high >= open+2,5%; selain itu jual di close.
- BPJS live: entry = harga saat alert; LOSS kalau low hari itu <= SL (di bawah open);
  WIN kalau high >= entry+2,5% (tidak tahu urutan intraday, jadi perkiraan kasar); selain itu jual di close.
- BSJP: entry = close hari sinyal; besok WIN kalau open/high >= entry+2%; LOSS kalau low <= SL;
  selain itu dianggap dijual di harga open.
"""
import sqlite3
from datetime import datetime, timedelta, timezone
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


RUNS = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tanggal TEXT, kind TEXT, jam TEXT,
    n_saham INTEGER, n_hari_ini INTEGER, n_kandidat INTEGER, n_baru INTEGER,
    gagal TEXT                    -- JSON: syarat yang paling sering tidak lolos
)"""


def conn():
    c = sqlite3.connect(config.DB_PATH)
    c.execute(SCHEMA)
    c.execute(RUNS)
    cols = {r[1] for r in c.execute("PRAGMA table_info(signals)")}
    for col, typ in [("skor", "INTEGER"), ("mode", "TEXT"), ("resep", "TEXT")]:   # migrasi DB lama
        if col not in cols:
            c.execute(f"ALTER TABLE signals ADD COLUMN {col} {typ}")
    return c


def save(info: dict, ai_pick: int | None, komentar: str = "") -> bool:
    """Simpan sinyal. Return True kalau baru (belum pernah tercatat hari itu)."""
    s = info["signal"]
    with conn() as c:
        cur = c.execute("""INSERT OR IGNORE INTO signals
            (tanggal,kode,tipe,close,entry,sl,tp1,rr,rsi,vol_ratio,skor,mode,resep,ai_pick,ai_komentar,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (info["tanggal"], info["kode"], s["tipe"], info["close"], s.get("entry"),
             s.get("sl"), s.get("tp1"), s.get("rr"), info["rsi"], info["vol_ratio"],
             s.get("skor"), s.get("mode", "swing"), s.get("resep"),
             ai_pick, komentar, datetime.now().isoformat(timespec="seconds")))
        return cur.rowcount == 1


def _evaluate(row: dict, df: pd.DataFrame) -> dict | None:
    if row.get("mode") == "bpjs_live":         # beli & jual di hari yang sama
        day = df[df.index == pd.Timestamp(row["tanggal"])]
        wib = datetime.now(timezone.utc) + timedelta(hours=7)
        if day.empty or (row["tanggal"] == wib.date().isoformat() and wib.hour < 17):
            return None                          # tunggu candle hari itu selesai
        bar, e = day.iloc[0], row["entry"]
        if bar["Low"] <= row["sl"]:              # konservatif: anggap kena cut dulu
            px, status = row["sl"], "LOSS"
        elif bar["High"] >= row["tp1"]:
            px, status = row["tp1"], "WIN"
        else:
            px = float(bar["Close"])
            status = "WIN" if px > e else "LOSS"
        return {"status": status, "exit_date": row["tanggal"], "exit_price": px,
                "result_pct": round((px / e - 1) * 100, 2), "hold_days": 0}

    after = df[df.index > pd.Timestamp(row["tanggal"])]
    if after.empty:
        return None

    mode = row.get("mode") or ("warning" if row["tipe"] in ("VAL_BREAKDOWN", "EXIT_WARNING") else "swing")

    if mode == "next_day" and (row.get("resep") or "").startswith("BPJS_DIP"):   # beli open, jual close
        bar = after.iloc[0]
        o = float(bar["Open"])
        px = float(bar["Close"])
        return {"status": "WIN" if px > o else "LOSS", "exit_date": str(after.index[0].date()),
                "exit_price": px, "result_pct": round((px / o - 1) * 100, 2), "hold_days": 1}

    if mode == "next_day":                     # BPJS: beli besok pagi
        bar = after.iloc[0]
        o, close0 = float(bar["Open"]), row["close"]
        base = {"exit_date": str(after.index[0].date()), "hold_days": 1}
        if o < close0 or o > close0 * 1.03:      # syarat masuk tidak terpenuhi
            return {**base, "status": "SKIP", "exit_price": o, "result_pct": 0.0}
        tp, sl = o * 1.025, close0 * 0.98
        if bar["Low"] <= sl:                     # konservatif: anggap kena cut dulu
            px, status = sl, "LOSS"
        elif bar["High"] >= tp:
            px, status = tp, "WIN"
        else:
            px = float(bar["Close"])
            status = "WIN" if px > o else "LOSS"
        return {**base, "status": status, "exit_price": px, "result_pct": round((px / o - 1) * 100, 2)}

    if mode == "bsjp":                         # BSJP: beli di close, jual besok pagi
        day = df[df.index == pd.Timestamp(row["tanggal"])]
        entry = float(day["Close"].iloc[0]) if len(day) else row["close"]
        bar = after.iloc[0]
        o = float(bar["Open"])
        if (row.get("resep") or "").startswith("BSJP_MOMBB"):   # riset: jual di open, apa pun hasilnya
            return {"status": "WIN" if o > entry else "LOSS", "exit_date": str(after.index[0].date()),
                    "exit_price": o, "result_pct": round((o / entry - 1) * 100, 2), "hold_days": 1}
        tp, sl = entry * 1.02, row["sl"] or entry * 0.97
        if o >= tp:
            px, status = o, "WIN"
        elif bar["High"] >= tp:
            px, status = tp, "WIN"
        elif bar["Low"] <= sl:
            px, status = sl, "LOSS"
        else:
            px = o                               # jual pagi, didekati dengan harga open
            status = "WIN" if px > entry else "LOSS"
        return {"status": status, "exit_date": str(after.index[0].date()), "exit_price": px,
                "result_pct": round((px / entry - 1) * 100, 2), "hold_days": 1}

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
           "skip": int((df["status"] == "SKIP").sum()) if len(df) else 0,
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
             f"Total tercatat {s['total']} · masih berjalan {s['open']} · "
             f"BPJS batal (syarat open tidak terpenuhi) {s['skip']}"]
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
                 f"maks {config.MAX_HOLD_DAYS} hari bursa; BPJS entry di open besok, BSJP di close. "
                 "Belum termasuk fee & slippage.</i>")
    return "\n".join(lines)


def bpjs_semalam(before: str) -> set[str]:
    """Kode di daftar BPJS dari scan malam terakhir sebelum tanggal `before`."""
    with conn() as c:
        row = c.execute("SELECT MAX(tanggal) FROM signals WHERE tipe='BPJS' AND tanggal < ?", (before,)).fetchone()
        if not row or not row[0]:
            return set()
        return {r[0] for r in c.execute("SELECT kode FROM signals WHERE tipe='BPJS' AND tanggal=?", (row[0],))}


def log_run(tanggal, kind, jam, n_saham, n_hari_ini, n_kandidat, n_baru, gagal: dict) -> None:
    import json
    with conn() as c:
        c.execute("INSERT INTO runs (tanggal,kind,jam,n_saham,n_hari_ini,n_kandidat,n_baru,gagal) "
                  "VALUES (?,?,?,?,?,?,?,?)",
                  (tanggal, kind, jam, n_saham, n_hari_ini, n_kandidat, n_baru, json.dumps(gagal)))


def runs_hari_ini(tanggal, kind) -> list[dict]:
    import json
    with conn() as c:
        c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute("SELECT * FROM runs WHERE tanggal=? AND kind=? ORDER BY id",
                                           (tanggal, kind))]
    for r in rows:
        r["gagal"] = json.loads(r["gagal"] or "{}")
    return rows


def sinyal_hari_ini(tanggal, tipe) -> list[str]:
    with conn() as c:
        return [r[0] for r in c.execute("SELECT kode FROM signals WHERE tanggal=? AND tipe=?", (tanggal, tipe))]
