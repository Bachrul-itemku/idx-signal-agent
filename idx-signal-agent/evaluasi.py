"""Evaluasi swing mingguan (dijalankan Sabtu, setelah riset otomatis BSJP/BPJS).

Prinsip sama dengan BSJP/BPJS: pakai cara dengan WINRATE tertinggi yang rata-ratanya tetap untung.
1. Backtest ±2 tahun semua tipe swing (hanya saat IHSG > MA50) di 300 saham terlikuid,
   bersih fee 0,4% + biaya 1 tick.
2. Tiap tipe diuji dengan beberapa jarak target jual: bawaan, 1R, 1,5R, 2R (R = jarak entry ke SL).
   Target lebih dekat biasanya menaikkan winrate.
3. Syarat sah: ≥50 trade, rata-rata positif, dan tidak rugi di ±6 bulan terakhir (kalau ≥10 trade).
4. Dipilih maks. 6 tipe dengan winrate (disusutkan untuk sampel kecil) tertinggi.
   Susunan lama hanya diganti kalau winrate rata-rata naik ≥2 poin."""
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import config
import data
import journal
import recipes
import signals
import strategi
import telegram_send
import universe
from indicators import round_tick, tick_size

VARIAN = ["bawaan", 1.0, 1.5, 2.0]
HARI = 480                 # ±2 tahun bursa
SAHAM = 300
TERBARU = 126              # ±6 bulan terakhir
MAKS_TIPE = 6


def _row(info, sig, k):
    tp = sig["tp1"]
    if k != "bawaan":
        tp = round_tick(sig["entry"] + k * (sig["entry"] - sig["sl"]), "up")
    return {"tanggal": info["tanggal"], "close": info["close"], "entry": sig["entry"], "sl": sig["sl"],
            "tp1": tp, "mode": "swing", "tipe": sig["tipe"], "resep": None}


def backtest(cache: dict) -> tuple[dict, str, int]:
    t0 = time.time()
    liquid = sorted(((float((df["Close"] * df["Volume"]).tail(250).mean()) / 1e9, k)
                     for k, df in cache.items() if len(df) > 300), reverse=True)
    liquid = [k for v, k in liquid if v >= config.MIN_VALUE_MILIAR][:SAHAM]
    pasar = data.pasar_series(cache, period="3y")
    semua_tgl = sorted({d for k in liquid for d in cache[k].index})
    batas_baru = str(semua_tgl[-TERBARU].date()) if len(semua_tgl) > TERBARU else ""
    trades = defaultdict(list)
    for n, kode in enumerate(liquid):
        df = cache[kode]
        mulai = max(260, len(df) - HARI)
        for i in range(mulai, len(df) - 1, 3):
            tgl = str(df.index[i].date())
            info = signals.analyze(kode, df.iloc[i - 259:i + 1], aktif=None, pasar=pasar.get(tgl, {}))
            for sig in (info or {}).get("signals", []):
                if sig["mode"] != "swing":
                    continue
                slip = tick_size(info["close"]) / info["close"] * 100
                for k in VARIAN:
                    res = journal._evaluate(_row(info, sig, k), df)
                    if res:
                        trades[(sig["tipe"], k)].append((tgl, res["result_pct"] - config.FEE_PCT - slip))
        if n % 50 == 0:
            print(f"[evaluasi] swing {n}/{len(liquid)} saham, {time.time() - t0:.0f} dtk")
    out = {}
    for key, xs in trades.items():
        r = [p for _, p in xs]
        b = [p for t, p in xs if t >= batas_baru]
        w = sum(p > 0 for p in r)
        out[key] = {"n": len(r), "wr": w / len(r), "ex": sum(r) / len(r),
                    "wr_adj": (w + 0.5 * 20) / (len(r) + 20),
                    "n_baru": len(b), "wr_baru": (sum(p > 0 for p in b) / len(b)) if b else 0.0,
                    "ex_baru": (sum(b) / len(b)) if b else 0.0}
    print(f"[evaluasi] backtest swing selesai {len(liquid)} saham, {time.time() - t0:.0f} dtk")
    return out, batas_baru, len(liquid)


def _sah(m):
    return m["n"] >= 50 and m["ex"] > 0 and (m["n_baru"] < 10 or m["ex_baru"] > 0)


def _nilai_susunan(bt, susunan: dict) -> float:
    ms = [bt.get((t, k)) for t, k in susunan.items()]
    ms = [m for m in ms if m]
    n = sum(m["n"] for m in ms)
    return sum(m["wr_adj"] * m["n"] for m in ms) / n if n else 0.0


def putuskan(aktif: dict, bt: dict, today: str) -> tuple[dict, list[str], dict]:
    baru = {**aktif, "riwayat": list(aktif.get("riwayat", []))}
    lama = {t: aktif.get("SWING_TP", {}).get(t, "bawaan") for t in aktif["SWING"]}
    terbaik = {}
    for t in recipes.SWING_SEMUA:
        calon = [(bt[(t, k)]["wr_adj"], bt[(t, k)]["ex"], k) for k in VARIAN
                 if (t, k) in bt and _sah(bt[(t, k)])]
        if calon:
            terbaik[t] = max(calon, key=lambda x: (x[0], x[1]))
    urut = sorted(terbaik.items(), key=lambda x: -x[1][0])[:MAKS_TIPE]
    usul = {t: v[2] for t, v in urut}
    skor_lama, skor_usul = _nilai_susunan(bt, lama), _nilai_susunan(bt, usul)
    catatan = []
    if not usul:
        catatan.append("⚠️ <b>Swing</b>: tidak ada tipe yang lolos (rata-rata untung). Susunan lama tetap.")
        pakai = lama
    elif not lama or skor_usul >= skor_lama + 0.02:
        pakai = usul
        baru["SWING"] = list(usul)
        baru["SWING_TP"] = {t: k for t, k in usul.items() if k != "bawaan"}
        baru["riwayat"].append({"tanggal": today, "kategori": "SWING", "dari": lama, "ke": usul})
        catatan.append(f"🔄 <b>Swing</b> diperbarui: winrate rata-rata {skor_lama:.0%} → {skor_usul:.0%}")
    else:
        pakai = lama
        catatan.append(f"✅ <b>Swing</b> tetap (winrate rata-rata {skor_lama:.0%}; penantang {skor_usul:.0%})")
    baru["riwayat"] = baru["riwayat"][-30:]
    return baru, catatan, pakai


def _k(k):
    return "target bawaan" if k == "bawaan" else f"target {str(k).replace('.', ',')}R"


def _d(x):
    return f"{x:+.2f}".replace(".", ",")


def laporan(catatan, bt, pakai, today, batas_baru, n_saham) -> str:
    p = [f"📈 <b>Evaluasi swing mingguan</b> · {today}",
         f"Backtest ±2 tahun, {n_saham} saham terlikuid, hanya saat IHSG &gt; MA50, bersih fee + 1 tick. "
         f"Dipilih winrate tertinggi yang rata-ratanya untung. \"Terbaru\" = sejak {batas_baru}."]
    p.append("<b>━━ Keputusan ━━</b>\n" + "\n".join(catatan))
    rows = []
    for t, k in pakai.items():
        m = bt.get((t, k))
        if m:
            rows.append(f"▶️ <code>{t}</code> · {_k(k)}: menang {m['wr']:.0%}, {_d(m['ex'])}%/trade ({m['n']} trade)"
                        f" · terbaru {m['wr_baru']:.0%}, {_d(m['ex_baru'])}% ({m['n_baru']})")
    p.append("<b>━━ Swing aktif ━━</b>\n" + ("\n".join(rows) or "-"))
    lain = []
    for t in recipes.SWING_SEMUA:
        if t in pakai:
            continue
        cands = [(bt[(t, k)], k) for k in VARIAN if (t, k) in bt]
        if cands:
            m, k = max(cands, key=lambda x: x[0]["wr_adj"])
            lain.append(f"✖️ <code>{t}</code> · {_k(k)}: menang {m['wr']:.0%}, {_d(m['ex'])}% ({m['n']})")
    if lain:
        p.append("<b>━━ Tidak dipakai ━━</b>\n" + "\n".join(lain))
    p.append("<i>Swing tetap hanya dikirim saat IHSG di atas MA50. Hasil masa lalu bukan jaminan.</i>")
    return "\n\n".join(p)


def run(cache: dict | None = None, kirim: bool = True) -> str:
    today = (datetime.now(timezone.utc) + timedelta(hours=7)).date().isoformat()
    aktif = strategi.load()
    if cache is None:
        cache = data.fetch_many(universe.scan_list(), period="3y")
    journal.update_open(lambda k: cache.get(k))
    bt, batas_baru, n_saham = backtest(cache)
    baru, catatan, pakai = putuskan(aktif, bt, today)
    if baru != aktif:
        strategi.save(baru)
    teks = laporan(catatan, bt, pakai, today, batas_baru, n_saham)
    if kirim:
        telegram_send.send(teks)
    return teks
