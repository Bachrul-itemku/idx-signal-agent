"""Varian resep dari skill saham-idx-hqbot. Evaluasi mingguan (evaluasi.py) menguji
semuanya dan memilih yang aktif; pilihan disimpan di strategi.json.

Setiap resep hanya memakai data OHLCV. Bagian resep yang butuh data bot
(NBS1, NF1D, BPR, TF) dibuang dan tetap dicek manual di @HQSahamIDX_bot."""

# ---------- BSJP (dinilai sore hari, candle hari itu) ----------
# b = bar_view: c,o,h,l,prev,chg,vol_adj,value_m,ma5,ma20,hc2d,tick,frac
# return (lolos_inti, [bonus...]) atau None


def _bsjp_longgar(b):
    # /SCORE100 IJO,KOKO,PASMA;20,TVAL;5,PCH;2;15 (BPR dicek di bot)
    core = (b["c"] > b["o"] and b["vol_adj"] > 1 and b["c"] > b["ma20"]
            and b["value_m"] >= 5 * b["frac"] and 2 <= b["chg"] <= 15)
    return core, [b["near_high"], b["vol_adj"] >= 2, b["value_m"] >= 10 * b["frac"], b["hc2d"]]


def _bsjp_ketat(b):
    # /SCORE100 IJO,CH,KOKO,PASMA;20,TVAL;5,PCH;2;15 — close harus = high
    core, bonus = _bsjp_longgar(b)
    return core and (b["h"] - b["c"]) <= b["tick"], bonus


def _bsjp_komunitas(b):
    # /SCORE100 TVAL;5,VSPIKE1,TF (TF dicek di bot)
    core = b["value_m"] >= 5 * b["frac"] and b["vol_adj"] >= 2 and b["c"] > b["o"] and b["chg"] <= 15
    return core, [b["near_high"], b["c"] > b["ma20"], b["hc2d"], 2 <= b["chg"]]


def _bsjp_hc2d(b):
    # /SCORE100 HC2D,PASMA;5,PASMA;20,TVAL;3 (+NBS1 di bot)
    core = (b["hc2d"] and b["c"] > b["ma5"] and b["c"] > b["ma20"]
            and b["value_m"] >= 3 * b["frac"] and b["chg"] <= 15)
    return core, [b["near_high"], b["vol_adj"] >= 1.5, b["value_m"] >= 10 * b["frac"], b["chg"] >= 2]


def _bsjp_mombb(b):
    # Riset 3 tahun: tembus upper BB + naik >4% + rata nilai 20 hari ≥50 M + harga 200–1000,
    # JUAL DI OPEN BESOK. WR 68% / 67% / 72% (train / valid / test), rata-rata +0,6%/trade bersih.
    core = (b["c"] > b["bb_up"] and b["chg"] > 4 and b["val_avg"] >= 50 and 200 <= b["c"] <= 1000)
    return core, [b["vol_adj"] >= 2, b["hc2d"], b["near_high"], b["chg"] <= 10]


BSJP = {
    "BSJP_MOMBB": ("Riset: tembus upper BB, naik >4%, rata nilai ≥50 M, harga 200–1000; jual di open", _bsjp_mombb),
    "BSJP_LONGGAR": ("IJO,KOKO,PASMA20,TVAL5,PCH 2–15%", _bsjp_longgar),
    "BSJP_KETAT": ("+ close = high (CH)", _bsjp_ketat),
    "BSJP_KOMUNITAS": ("TVAL5 + VSPIKE1", _bsjp_komunitas),
    "BSJP_HC2D": ("HC2D,PASMA5,PASMA20,TVAL3", _bsjp_hc2d),
}

# ---------- BPJS malam (dinilai setelah close, eksekusi besok pagi) ----------
# f = hasil signals._filters (kode /SCORE) → return skor 0..100 (0 = tidak lolos)


def _bpjs_skor8(f):
    keys = ["IJO", "KOKO", "PASMA20", "HC2D", "TVAL3", "PCH_2_8", "VSPIKE1", "HHHL"]
    skor = round(100 * sum(f[k] for k in keys) / len(keys))
    return skor if skor >= 75 and f["IJO"] and f["PASMA20"] and f["TVAL3"] else 0


def _bpjs_koko(f):
    # /SCORE100 IJO,KOKO,PASMA;20,NF1D,PCH;2;8 (NF1D dicek di bot)
    ok = f["IJO"] and f["KOKO"] and f["PASMA20"] and f["PCH_2_8"]
    return (75 + 25 * f["TVAL3"]) if ok else 0


def _bpjs_hc2d(f):
    # /SCORE100 HC2D,PASMA;5,PASMA;20,TVAL;3,NBS1 (NBS1 dicek di bot)
    ok = f["HC2D"] and f["PASMA5"] and f["PASMA20"] and f["TVAL3"]
    return (75 + 25 * f["KOKO"]) if ok else 0


def _bpjs_green_hammer(f):
    # Green hammer: /SCORE100 IJO,CLOSEHIGH,TAIL;3 + PASMA20
    ok = f["IJO"] and f["HAMMER"] and f["PASMA20"] and f["TVAL1"]
    return (75 + 25 * f["VSPIKE1"]) if ok else 0


def _bpjs_dip(f):
    # Riset 3 tahun: buy the dip saat pasar panik. Turun >4%, close di bawah lower BB, IHSG turun >1%,
    # rata nilai ≥10 M. Beli di open besok, jual di close besok.
    # WR 57% / 57% / 59%, rata-rata +0,6% / +2,1% / +2,1% per trade bersih.
    ok = f["TURUN4"] and f["BB_BAWAH"] and f["IHSG_TURUN1"] and f["RATA10"]
    return 100 if ok else 0


BPJS = {
    "BPJS_DIP": ("Riset: turun >4%, di bawah lower BB, IHSG turun >1%; beli open, jual close", _bpjs_dip),
    "BPJS_SKOR8": ("≥6 dari 8 filter (IJO,KOKO,PASMA20,HC2D,TVAL3,PCH,VSPIKE1,HHHL)", _bpjs_skor8),
    "BPJS_KOKO": ("IJO,KOKO,PASMA20,PCH 2–8%", _bpjs_koko),
    "BPJS_HC2D": ("HC2D,PASMA5,PASMA20,TVAL3", _bpjs_hc2d),
    "BPJS_GREEN_HAMMER": ("IJO + hammer + PASMA20", _bpjs_green_hammer),
}

# ---------- Swing ----------
SWING_SEMUA = ["BASE_RECOVERY", "VP_VAL_BOUNCE", "VP_VAH_BREAKOUT", "FR4_BREAKOUT", "FR2_PULLBACK", "FCAAK",
               "MA_GC", "STATS_REV", "BB_BOUNCE", "GZ_FIBO", "HBO_VOL"]
SWING_AWAL = ["VP_VAL_BOUNCE", "VP_VAH_BREAKOUT", "FR4_BREAKOUT", "FR2_PULLBACK", "FCAAK",
              "MA_GC", "STATS_REV"]

# BASE_RECOVERY sengaja tidak aktif: riset menunjukkan hanya bagus di saham dekat gocap & pasar naik,
# negatif setelah biaya 1 tick. Tetap ikut diuji evaluasi mingguan.
DEFAULT = {"BSJP": "BSJP_MOMBB", "BPJS": "BPJS_DIP", "SWING": list(SWING_AWAL), "riwayat": []}
