"""Sinyal dari pengetahuan skill saham-idx-hqbot (Volume Profile, Fractal FR1–FR5,
FCAAK, golden cross, Stats Rev, BPJS), dihitung ulang dari data OHLCV.

Yang TIDAK bisa dihitung di sini (butuh data @HQSahamIDX_bot): NBS1/AC3D (broker),
NF3D (asing), MFQ (frekuensi), BPR/BOR (bid-offer). Untuk itu tiap sinyal membawa
perintah verifikasi yang bisa langsung diketik di bot.

Angka entry/SL/TP HANYA dihitung di sini; AI tidak boleh mengubahnya."""
import math
import config
import recipes
from indicators import (volume_profile, enrich, round_tick, tick_size,
                        fractals, bullish_divergence)

NAMA = {
    "VP_VAL_BOUNCE": "🟢 VAL Bounce (Volume Profile)",
    "VP_VAH_BREAKOUT": "🚀 VAH Breakout (Volume Profile)",
    "FR4_BREAKOUT": "🚀 FR4 Breakout fractal merah",
    "FR2_PULLBACK": "🟢 FR2 Pullback ke fractal hijau",
    "FCAAK": "🧲 FCAAK (jejak akumulasi)",
    "MA_GC": "✨ Golden Cross MA20/50",
    "STATS_REV": "↩️ Reversal dari low 52 minggu",
    "BB_BOUNCE": "🟢 Pantul lower Bollinger (BB15)",
    "GZ_FIBO": "🟡 Golden zone Fibo 90 hari",
    "HBO_VOL": "🚀 Breakout high 20 hari + volume",
    "BPJS": "☀️ BPJS (beli pagi jual sore)",
    "BSJP": "🌙 BSJP (beli sore jual pagi)",
    "BPJS_LIVE": "⚡ BPJS live (beli pagi jual sore)",
    "EXIT_WARNING": "🔴 Peringatan exit",
}

# Perintah verifikasi di @HQSahamIDX_bot ({k} = kode saham)
VERIFIKASI = {
    "VP_VAL_BOUNCE": ["/VPC {k}", "/SCORE2 HMR,BULLPB,TAIL;3,NBS1 {k}", "/ACCUMBD {k}"],
    "VP_VAH_BREAKOUT": ["/VPC {k}", "/SCORE2 VSPIKE1;20,HBO;20,NBS1 {k}"],
    "FR4_BREAKOUT": ["/C {k} F5", "/SCORE2 FR4,VSPIKE1,NBS1,AC3D;U,NORETAIL {k}", "/PNBSRATIO {k} 5 10"],
    "FR2_PULLBACK": ["/C {k} F5", "/SCORE2 FR2,GZFIBO90,NBS1,AC5D;D {k}"],
    "FCAAK": ["/C {k} P1,O5,I59,I106", "/MFQHIS {k}", "/PNBSRATIO {k} 5 3"],
    "MA_GC": ["/C {k} MA20,MA50,Z720", "/SCORE2 NGCSMA;20;50,AC3D,NF3D {k}"],
    "STATS_REV": ["/STATS {k}", "/SCORE2 HMR,ACREV,NBS1 {k}"],
    "BB_BOUNCE": ["/C {k} P1,O5,I59,I106", "/SCORE2 BB15,NBS1 {k}"],
    "GZ_FIBO": ["/FIBO90 {k}", "/SCORE2 GZFIBO90,NBS1 {k}"],
    "HBO_VOL": ["/C {k} MA20,MA50", "/SCORE2 HBO;20,VSPIKE1,NBS1 {k}"],
    "BPJS": ["malam: /SCORE2 NBS1,NF1D {k}", "pagi 09.15: /MFQ {k} 1", "pagi: /BOR {k}"],
    "BSJP": ["/BOR {k}", "/MFQ {k} 1", "/SCORE2 BPR;2,NBS1;1 {k}"],
    "BPJS_LIVE": ["/BOR {k}", "/MFQ {k} 1", "/SCORE2 OL,BPR;3,TF {k}"],
    "EXIT_WARNING": ["/C {k} F5", "/SCORE2 FR5,NBS2 {k}"],
}


def rp(x) -> str:
    return f"{x:,.0f}".replace(",", ".")


def _filters(df) -> dict:
    """Filter ala kode /SCORE, untuk candle terakhir."""
    last, p1, p2 = df.iloc[-1], df.iloc[-2], df.iloc[-3]
    c, o, h, l, v = last["Close"], last["Open"], last["High"], last["Low"], last["Volume"]
    t = tick_size(c)
    body = abs(c - o)
    rng = max(h - l, t)
    chg = (c / p1["Close"] - 1) * 100
    value_m = c * v / 1e9
    vol_ratio = v / last["VolMA20"] if last["VolMA20"] else 0

    hi90, lo90 = df["High"].tail(90).max(), df["Low"].tail(90).min()
    pos90 = (c - lo90) / (hi90 - lo90) if hi90 > lo90 else 0.5   # 0 = low 90 hari, 1 = high

    width = df["BB_width"]
    squeeze_lvl = width.tail(120).quantile(0.15)

    ma20, ma50 = df["MA20"], df["MA50"]
    gc_recent = any(ma20.iloc[-i] > ma50.iloc[-i] and ma20.iloc[-i - 1] <= ma50.iloc[-i - 1] for i in range(1, 4))

    return {
        "IJO": c > o,
        "CH": h - c <= t,                                   # close = high
        "HAMMER": (min(c, o) - l) >= 2 * body and (h - max(c, o)) <= max(body, t) and (c - l) / rng >= 0.6,
        "KOKO": vol_ratio > 1 and value_m > 1 and chg > 2,  # vol>MA20, value>1M, naik>2%
        "VSPIKE1": vol_ratio >= 2 and c > o,
        "PASMA5": c > last["MA5"],
        "PASMA20": c > last["MA20"],
        "PASMA50": c > last["MA50"],
        "TVAL1": value_m >= 1, "TVAL3": value_m >= 3, "TVAL5": value_m >= 5,
        "PCH_2_8": 2 <= chg <= 8,
        "HC2D": c > p1["Close"] > p2["Close"],
        "HHHL": h > p1["High"] and l > p1["Low"],
        "BB_SQUEEZE": bool((width.tail(5) <= squeeze_lvl).any()),
        "NEAR_LOWER_BB": l <= last["BB_low"] * 1.02,
        "RSI_DIV": bullish_divergence(df["Close"], df["RSI"]),
        "FIB_BOTTOM": pos90 <= 0.382,                       # retrace ≥ 61,8% dari high 90 hari
        "FIB_GZ": 0.214 <= pos90 <= 0.382,                  # golden zone 61,8–78,6%
        "SMAGC_20_50": gc_recent,
        "_chg": chg, "_vol_ratio": vol_ratio, "_value_m": value_m,
    }


def _plan(entry, sl, tp):
    if sl is None or tp is None or entry <= sl:
        return None
    rr = (tp - entry) / (entry - sl)
    if rr < config.MIN_RR:
        return None
    risk_rp = config.MODAL_RP * config.RISK_PCT / 100
    lot = min(math.floor(risk_rp / ((entry - sl) * 100)), math.floor(config.MODAL_RP / (entry * 100)))
    return {"entry": float(entry), "sl": sl, "tp1": tp, "rr": round(rr, 2), "lot": max(lot, 0)}


def plan_bpjs(close: float) -> dict:
    """Rencana beli pagi jual sore (kaidah HQSaham), angka dari close hari ini."""
    return {
        "entry": close,
        "beli_bawah": round_tick(close, "down"),
        "beli_atas": round_tick(close * 1.02, "down"),
        "open_maks": round_tick(close * 1.03, "down"),      # gap terlalu tinggi = jangan kejar
        "tp1": round_tick(close * 1.025, "up"),
        "tp2": round_tick(close * 1.04, "up"),
        "sl": round_tick(close * 0.98, "down"),             # batas keras kalau low 15 menit tak jelas
        "rr": None, "lot": None,
    }


def plan_bsjp(price: float, low_today: float) -> dict:
    """Rencana beli sore jual pagi, angka dari harga saat scan (±15 menit telat)."""
    t = tick_size(price)
    return {
        "entry": price,
        "beli_bawah": round_tick(price - t, "down"),
        "beli_atas": round_tick(price + 2 * t, "down"),
        "jangan_di_atas": round_tick(price * 1.02, "up"),    # sudah lari, jangan kejar
        "tp1": round_tick(price * 1.02, "up"),
        "tp2": round_tick(price * 1.03, "up"),
        "sl": round_tick(max(low_today - t, price * 0.97), "down"),
        "rr": None, "lot": None,
    }


def session_fraction(now) -> float:
    """Porsi jam perdagangan yang sudah lewat (untuk membandingkan volume parsial hari ini
    dengan rata-rata volume harian). Sesi Senin–Kamis 09.00–12.00 & 13.30–15.50,
    Jumat 09.00–11.30 & 14.00–15.50. `now` sudah dikurangi keterlambatan data."""
    m = now.hour * 60 + now.minute
    if now.weekday() == 4:
        s1, s2 = (540, 690), (840, 950)
    else:
        s1, s2 = (540, 720), (810, 950)
    total = (s1[1] - s1[0]) + (s2[1] - s2[0])
    done = max(0, min(m, s1[1]) - s1[0]) + max(0, min(m, s2[1]) - s2[0])
    return max(done / total, 0.05)


def bar_view(dfe, i: int = -1, frac: float = 1.0) -> dict:
    """Angka candle ke-i dari df yang sudah di-enrich. Rata-rata memakai hari SEBELUMNYA,
    jadi bisa dipakai untuk candle yang belum selesai (live) maupun backtest."""
    row = dfe.iloc[i]
    c, o, h, l, v = (float(row["Close"]), float(row["Open"]), float(row["High"]),
                     float(row["Low"]), float(row["Volume"]))
    p1, p2 = float(dfe["Close"].iloc[i - 1]), float(dfe["Close"].iloc[i - 2])
    vol_avg = float(row["VolAvgPrev"]) if row["VolAvgPrev"] == row["VolAvgPrev"] else 0
    return {
        "c": c, "o": o, "h": h, "l": l, "prev": p1, "frac": frac, "tick": tick_size(c),
        "chg": (c / p1 - 1) * 100,
        "value_m": c * v / 1e9, "val_avg": float(row["ValAvgPrev"]) / 1e9,
        "vol_adj": v / (vol_avg * frac) if vol_avg else 0,
        "ma5": float(row["MA5prev"]), "ma20": float(row["MA20prev"]),
        "hc2d": c > p1 > p2, "near_high": (h - c) / c <= 0.01,
        "rsi": float(row["RSI"]), "tanggal": str(dfe.index[i].date()),
    }


def _pack(kode, b, tipe, mode, skor, alasan, plan):
    return {
        "kode": kode, "tanggal": b["tanggal"], "close": b["c"],
        "chg_pct": round(b["chg"], 2), "vol_ratio": round(b["vol_adj"], 2),
        "value_miliar": round(b["value_m"], 2), "rsi": round(b["rsi"], 1),
        "signal": {"tipe": tipe, "skor": skor, "mode": mode, "alasan": alasan, **plan},
    }


def bsjp_dari_bar(kode, b, resep: str) -> dict | None:
    if b["c"] < config.MIN_PRICE or b["val_avg"] < config.MIN_VALUE_MILIAR:
        return None
    core, bonus = recipes.BSJP[resep][1](b)
    if not core:
        return None
    alasan = (f"Resep {resep}; " + ("dekat high hari ini" if b["near_high"] else "agak jauh dari high")
              + f", volume {b['vol_adj']:.1f}x normal".replace(".", ","))
    return {
        "kode": kode, "tanggal": b["tanggal"], "close": b["c"],
        "chg_pct": round(b["chg"], 2), "vol_ratio": round(b["vol_adj"], 2),
        "value_miliar": round(b["value_m"], 2), "rsi": round(b["rsi"], 1),
        "signal": {"tipe": "BSJP", "skor": _score(True, bonus), "mode": "bsjp", "resep": resep,
                   "alasan": alasan, **plan_bsjp(b["c"], b["l"])},
    }


def bsjp(kode: str, df, frac: float = 1.0, resep: str | None = None) -> dict | None:
    """BSJP live (15.00–15.50 WIB) dengan resep aktif dari strategi.json."""
    if len(df) < 30:
        return None
    b = bar_view(enrich(df), -1, frac)
    return bsjp_dari_bar(kode, b, resep or recipes.DEFAULT["BSJP"])


def plan_bpjs_live(price: float, open_: float) -> dict:
    t = tick_size(price)
    entry = price
    return {
        "entry": entry,
        "beli_bawah": round_tick(price - t, "down"),
        "beli_atas": round_tick(price + 2 * t, "down"),
        "jangan_di_atas": round_tick(price * 1.02, "up"),
        "tp1": round_tick(entry * 1.025, "up"),
        "tp2": round_tick(entry * 1.04, "up"),
        "sl": round_tick(open_ - t, "down"),              # open = low: jebol open = gagal
        "rr": None, "lot": None,
    }


def bpjs_live(kode: str, df, frac: float, watch_semalam: set) -> dict | None:
    """BPJS live (09.00–11.00 WIB). Resep pagi skill:
    /SCORE100 OL,BPR;3,TF,VSPIKE1,TVAL;3,PASMA;20,PCH;1;5 (BPR & TF dicek di bot)."""
    if len(df) < 30:
        return None
    b = bar_view(enrich(df), -1, frac)
    c, o, l = b["c"], b["o"], b["l"]
    if c < config.MIN_PRICE or b["val_avg"] < config.MIN_VALUE_MILIAR:
        return None
    t = tick_size(c)
    open_low = (o - l) <= t                                   # OL: open = low (belum pernah di bawah open)
    core = (open_low and c > o and c > b["ma20"] and 1 <= b["chg"] <= 5
            and b["vol_adj"] >= 1.5 and b["value_m"] >= max(0.5, 3 * frac))
    if not core:
        return None
    near_high = (b["h"] - c) / c <= 0.01
    semalam = kode in watch_semalam
    bonus = [semalam, near_high, b["vol_adj"] >= 3, b["value_m"] >= 10 * frac]
    alasan = "Open = low, naik di atas open" + (", ⭐ ada di daftar BPJS semalam" if semalam else "") + \
             f", volume {b['vol_adj']:.1f}x normal".replace(".", ",")
    return _pack(kode, b, "BPJS_LIVE", "bpjs_live", _score(True, bonus), alasan, plan_bpjs_live(c, o))


def _score(core_ok: bool, bonus: list[bool]) -> int:
    if not core_ok:
        return 0
    return round(50 + 50 * sum(bonus) / len(bonus)) if bonus else 100


def analyze(kode: str, df, aktif: dict | None = None) -> dict | None:
    """aktif = isi strategi.json (resep BPJS & daftar tipe swing yang dipakai).
    aktif=None: semua tipe swing dihitung (dipakai backtest)."""
    if len(df) < max(config.VP_LOOKBACK, 130):
        return None
    df = enrich(df)
    last, prev = df.iloc[-1], df.iloc[-2]
    c, o, l = float(last["Close"]), float(last["Open"]), float(last["Low"])
    if c < config.MIN_PRICE or float(last["ValueMA20"]) / 1e9 < config.MIN_VALUE_MILIAR:
        return None                                         # gocap / tidak likuid: lewati
    t = tick_size(c)
    f = _filters(df)
    vp = volume_profile(df.tail(config.VP_LOOKBACK))
    red, green = fractals(df)
    reds, greens = red.dropna(), green.dropna()
    last_red = float(reds.iloc[-1]) if len(reds) else None
    last_green = float(greens.iloc[-1]) if len(greens) else None

    info = {
        "kode": kode, "tanggal": str(df.index[-1].date()), "close": c,
        "chg_pct": round(f["_chg"], 2), "vol_ratio": round(f["_vol_ratio"], 2),
        "value_miliar": round(f["_value_m"], 2),
        "value_ma20_miliar": round(float(last["ValueMA20"]) / 1e9, 2),
        "rsi": round(float(last["RSI"]), 1),
        "ma20": round(float(last["MA20"])), "ma50": round(float(last["MA50"])),
        "poc": round(vp["poc"]), "vah": round(vp["vah"]), "val": round(vp["val"]),
        "fractal_merah": last_red, "fractal_hijau": last_green,
        "filter_lolos": sorted(k for k, v in f.items() if not k.startswith("_") and v),
        "signals": [],
    }
    if info["value_ma20_miliar"] < config.MIN_VALUE_MILIAR:
        return info                                         # tidak likuid

    out = []

    def add(tipe, skor, plan=None, mode="swing", alasan=""):
        if skor <= 0 or (mode == "swing" and plan is None):
            return
        out.append({"tipe": tipe, "skor": skor, "mode": mode, "alasan": alasan,
                    **(plan or {"entry": None, "sl": None, "tp1": None, "rr": None, "lot": None})})

    near_poc = abs(c - vp["poc"]) / vp["poc"] < 0.01        # jebakan #1: jangan entri di POC
    body, lower_wick = abs(c - o), min(c, o) - l

    # 1) Volume Profile — VAL bounce (rejection di VAL, target POC)
    core = l <= vp["val"] * 1.01 and c > vp["val"] and c >= o and lower_wick >= body and not near_poc
    add("VP_VAL_BOUNCE", _score(core, [f["HAMMER"], f["NEAR_LOWER_BB"], f["FIB_BOTTOM"], f["RSI_DIV"]]),
        _plan(c, round_tick(vp["val"] - 2 * t), round_tick(vp["poc"])),
        alasan="Sentuh VAL lalu ditolak; target POC")

    # 2) Volume Profile — VAH breakout (wajib lonjakan volume)
    core = c > vp["vah"] and prev["Close"] <= vp["vah"] and f["_vol_ratio"] >= config.BREAKOUT_VOL_RATIO
    sl = round_tick(vp["vah"] - 2 * t)
    add("VP_VAH_BREAKOUT", _score(core, [f["CH"], f["TVAL5"], f["HHHL"], f["PASMA50"]]),
        _plan(c, sl, round_tick(c + 2 * (c - sl))), alasan="Close tembus VAH dengan volume")

    # 3) FR4 — breakout fractal merah, wajib konfirmasi volume (VSPIKE1/KOKO)
    if last_red and last_green:
        core = c > last_red and prev["Close"] <= last_red and (f["VSPIKE1"] or f["KOKO"])
        sl = round_tick(last_green - 2 * t)
        add("FR4_BREAKOUT", _score(core, [f["PASMA20"], f["TVAL5"], f["CH"], f["HHHL"]]),
            _plan(c, sl, round_tick(c + 2 * (c - sl))),
            alasan=f"Tembus fractal merah {rp(last_red)}; SL di bawah fractal hijau")

    # 4) FR2 — fractal hijau terkonfirmasi, harga koreksi mendekatinya (buy on weakness)
    if last_green:
        recent_green = greens.index[-1] >= df.index[-15]
        core = recent_green and last_green < c <= last_green * 1.04 and c < prev["Close"] and f["PASMA50"]
        above = reds[reds > c]
        tp = round_tick(float(above.iloc[-1])) if len(above) else None
        sl = round_tick(last_green - 2 * t)
        add("FR2_PULLBACK", _score(core, [f["HAMMER"], f["FIB_GZ"], f["TVAL3"], last["RSI"] < 50]),
            _plan(c, sl, tp or round_tick(c + 2 * (c - sl))),
            alasan="Koreksi mendekati fractal hijau; target fractal merah terdekat")

    # 5) FCAAK — 4 pilar: squeeze, bullish divergence, spike, posisi bottom
    #    (spike frekuensi I106 tidak tersedia → dipakai spike volume sebagai pendekatan)
    pilar = [f["BB_SQUEEZE"], f["RSI_DIV"], f["VSPIKE1"], f["FIB_BOTTOM"] or f["NEAR_LOWER_BB"]]
    core = f["RSI_DIV"] and sum(pilar) >= 3
    sl = round_tick(float(df["Low"].tail(20).min()) - 2 * t)
    tp = round_tick(float(last["BB_mid"]))
    plan = _plan(c, sl, tp) or _plan(c, sl, round_tick(float(last["BB_up"])))
    add("FCAAK", _score(core, pilar), plan,
        alasan=f"{sum(pilar)}/4 pilar FCAAK (squeeze, divergence, spike volume, area bottom)")

    # 6) Golden cross MA20/MA50 (resep admin; AC3D/NF3D dicek di bot)
    core = f["SMAGC_20_50"] and f["TVAL1"]
    sl = round_tick(float(df["Low"].tail(10).min()) - 2 * t)
    add("MA_GC", _score(core, [f["PASMA20"], f["VSPIKE1"], f["HHHL"], f["IJO"]]),
        _plan(c, sl, round_tick(c + 2 * (c - sl))), alasan="MA20 baru memotong MA50 ke atas")

    # 7) Stats Rev — memantul dari low 52 minggu
    lo52 = float(df["Low"].tail(250).min())
    core = (df["Low"].tail(10).min() <= lo52) and lo52 * 1.03 <= c <= lo52 * 1.15 and f["IJO"]
    sl = round_tick(lo52 - 2 * t)
    add("STATS_REV", _score(core, [f["HAMMER"], f["VSPIKE1"], f["RSI_DIV"], f["TVAL3"]]),
        _plan(c, sl, round_tick(c + 2 * (c - sl))), alasan=f"Memantul dari low 52 minggu {rp(lo52)}")

    # 8) Swing tambahan dari katalog FCAAK/HQ (ikut diuji tiap minggu)
    # BB15: pantul dari lower band
    core = f["NEAR_LOWER_BB"] and c > float(last["BB_low"]) and f["IJO"] and not near_poc
    sl = round_tick(l - 2 * t)
    add("BB_BOUNCE", _score(core, [f["HAMMER"], f["RSI_DIV"], f["VSPIKE1"], f["TVAL3"]]),
        _plan(c, sl, round_tick(float(last["BB_mid"]))) or _plan(c, sl, round_tick(c + 2 * (c - sl))),
        alasan="Memantul dari lower Bollinger Band (BB15)")
    # GZFIBO90: di golden zone 61,8–78,6% + candle hijau
    core = f["FIB_GZ"] and f["IJO"] and f["TVAL1"]
    lo90 = float(df["Low"].tail(90).min())
    sl = round_tick(lo90 - 2 * t)
    add("GZ_FIBO", _score(core, [f["HAMMER"], f["RSI_DIV"], f["PASMA50"], f["VSPIKE1"]]),
        _plan(c, sl, round_tick(c + 2 * (c - sl))), alasan="Di golden zone Fibo 90 hari (GZFIBO90)")
    # HBO;20 + VSPIKE1: tembus high 20 hari dengan volume
    hi20 = float(df["High"].iloc[-21:-1].max())
    core = c > hi20 and float(prev["Close"]) <= hi20 and f["VSPIKE1"] and f["TVAL3"]
    sl = round_tick(float(df["Low"].tail(10).min()) - 2 * t)
    add("HBO_VOL", _score(core, [f["CH"], f["PASMA50"], f["HHHL"], f["TVAL5"]]),
        _plan(c, sl, round_tick(c + 2 * (c - sl))), alasan=f"Tembus high 20 hari {rp(hi20)} dengan volume")

    # 9) BPJS — screening malam dengan resep aktif, dieksekusi besok pagi
    resep_bpjs = (aktif or recipes.DEFAULT)["BPJS"]
    skor = recipes.BPJS[resep_bpjs][1](f)
    if skor:
        add("BPJS", skor, {**plan_bpjs(c), "resep": resep_bpjs}, mode="next_day", alasan=f"Resep {resep_bpjs}")

    # 10) Peringatan exit: FR5 (fractal hijau jebol) atau breakdown VAL
    alasan = []
    if last_green and c < last_green and prev["Close"] >= last_green:
        alasan.append(f"FR5: jebol fractal hijau {rp(last_green)}")
    if c < vp["val"] and prev["Close"] >= vp["val"]:
        alasan.append(f"close di bawah VAL {rp(vp['val'])}")
    if alasan:
        add("EXIT_WARNING", 100, mode="warning", alasan="; ".join(alasan))

    if aktif is not None:                                   # hanya tipe swing yang aktif
        out = [x for x in out if x["mode"] != "swing" or x["tipe"] in aktif["SWING"]]
    info["signals"] = sorted(out, key=lambda s: -s["skor"])
    return info
