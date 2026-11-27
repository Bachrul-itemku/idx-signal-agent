"""Evaluasi mingguan (Sabtu pagi):
1. Performa LIVE dari jurnal: 7 hari terakhir vs 28 hari sebelumnya, per jenis sinyal.
2. BACKTEST ±6 bulan semua varian resep (BSJP, BPJS malam, swing) di saham paling likuid,
   hasil dipotong perkiraan fee. Dinilai: 6 bulan penuh & 4 minggu terakhir.
3. Kalau resep aktif MENURUN dan ada varian yang jelas lebih bagus → ganti otomatis
   (strategi.json), dengan pengaman supaya tidak gonta-ganti karena kebetulan.

Batasan backtest: hanya data harian. BSJP dinilai dari candle penuh (aslinya dinilai
±15.00), urutan intraday tidak diketahui (kalau SL & TP tersentuh di hari yang sama
dianggap kena SL), dan sinyal teratas per hari tidak dibatasi 10 seperti live."""
import html
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import pandas as pd
import config
import data
import journal
import recipes
import signals
import strategi
import telegram_send
import universe
from indicators import enrich

MIN_N_6B, MIN_N_4M = 30, 8          # minimal trade supaya angkanya berarti
MARGIN = 0.2                         # resep baru harus unggul ≥0,2% per trade (6 bulan)
COOLDOWN_HARI = 13                   # jangan ganti kategori yang sama dua minggu berturut


def _row(r):
    s = r["signal"]
    return {"tanggal": r["tanggal"], "close": r["close"], "entry": s.get("entry"), "sl": s.get("sl"),
            "tp1": s.get("tp1"), "mode": s["mode"], "tipe": s["tipe"], "resep": s.get("resep")}


def _metrics(trades, batas_4m: str) -> dict:
    """trades = [(tanggal_sinyal, hasil_bersih_%)]"""
    def m(xs):
        if not xs:
            return {"n": 0, "wr": 0.0, "exp": 0.0}
        return {"n": len(xs), "wr": round(100 * sum(x > 0 for x in xs) / len(xs), 1),
                "exp": round(sum(xs) / len(xs), 2)}
    return {"6b": m([p for _, p in trades]), "4m": m([p for t, p in trades if t >= batas_4m])}


def backtest(cache: dict) -> tuple[dict, str, int]:
    """Return ({(kategori, nama): metrics}, tanggal_awal_4_minggu, jumlah_saham_diuji)."""
    t0 = time.time()
    liquid = []
    for kode, df in cache.items():
        if len(df) < 300:
            continue
        val = float((df["Close"] * df["Volume"]).tail(20).mean()) / 1e9
        if val >= config.MIN_VALUE_MILIAR and float(df["Close"].iloc[-1]) >= config.MIN_PRICE:
            liquid.append((val, kode))
    liquid = [k for _, k in sorted(liquid, reverse=True)[:config.BT_MAX_SAHAM]]

    pasar = data.pasar_series(cache, period="3y")
    trades = defaultdict(list)
    tanggal_uji = set()
    for n, kode in enumerate(liquid):
        df = cache[kode]
        dfe = enrich(df)
        start = len(df) - config.BT_HARI
        for i in range(start, len(df) - 1):          # hari terakhir belum punya hasil
            tgl = str(df.index[i].date())
            tanggal_uji.add(tgl)
            b = signals.bar_view(dfe, i, 1.0)
            b["ihsg_ret5"] = pasar.get(tgl, {}).get("ihsg_ret5", 0)
            if b["c"] < config.MIN_PRICE or not (b["val_avg"] >= config.MIN_VALUE_MILIAR):
                continue
            # BSJP
            for nama in recipes.BSJP:
                r = signals.bsjp_dari_bar(kode, b, nama)
                if r:
                    res = journal._evaluate(_row(r), df)
                    if res:
                        trades[("BSJP", nama)].append((tgl, res["result_pct"] - config.FEE_PCT))
            # BPJS malam (eksekusi besok pagi)
            ps = pasar.get(tgl, {})
            f = signals._filters(dfe.iloc[:i + 1], ps)
            if f["TERKUNCI"]:
                continue
            for nama, (_, fn) in recipes.BPJS.items():
                if fn(f):
                    r = {"tanggal": tgl, "close": b["c"],
                         "signal": {**signals.plan_bpjs(b["c"]), "mode": "next_day", "tipe": "BPJS",
                                    "resep": nama}}
                    res = journal._evaluate(_row(r), df)
                    if res and res["status"] != "SKIP":
                        trades[("BPJS", nama)].append((tgl, res["result_pct"] - config.FEE_PCT))
            # Swing (tiap 3 hari supaya cepat)
            if (i - start) % 3 == 0:
                info = signals.analyze(kode, df.iloc[max(0, i - 259):i + 1], aktif=None, pasar=ps)
                for sig in (info or {}).get("signals", []):
                    if sig["mode"] != "swing":
                        continue
                    res = journal._evaluate(_row({**info, "signal": sig}), df)
                    if res:
                        trades[("SWING", sig["tipe"])].append((tgl, res["result_pct"] - config.FEE_PCT))
        if n % 50 == 0:
            print(f"[evaluasi] backtest {n}/{len(liquid)} saham, {time.time() - t0:.0f} detik")

    hari = sorted(tanggal_uji)
    batas_4m = hari[-20] if len(hari) >= 20 else (hari[0] if hari else "")
    hasil = {k: _metrics(v, batas_4m) for k, v in trades.items()}
    for nama in recipes.BSJP:
        hasil.setdefault(("BSJP", nama), _metrics([], batas_4m))
    for nama in recipes.BPJS:
        hasil.setdefault(("BPJS", nama), _metrics([], batas_4m))
    for t in recipes.SWING_SEMUA:
        hasil.setdefault(("SWING", t), _metrics([], batas_4m))
    print(f"[evaluasi] backtest selesai {len(liquid)} saham, {time.time() - t0:.0f} detik")
    return hasil, batas_4m, len(liquid)


def live_stats(today: str) -> dict:
    """{tipe: {"minggu": m, "sebelum": m}} dari jurnal, hasil bersih fee."""
    with journal.conn() as c:
        df = pd.read_sql("SELECT tipe, exit_date, result_pct, status FROM signals "
                         "WHERE status IN ('WIN','LOSS','EXPIRED')", c)
    out = {}
    if df.empty:
        return out
    d0 = pd.Timestamp(today)
    df["exit"] = pd.to_datetime(df["exit_date"])
    df["net"] = df["result_pct"] - config.FEE_PCT
    for tipe, g in df.groupby("tipe"):
        mg = g[g["exit"] > d0 - pd.Timedelta(days=7)]["net"]
        sb = g[(g["exit"] <= d0 - pd.Timedelta(days=7)) & (g["exit"] > d0 - pd.Timedelta(days=35))]["net"]
        f = lambda s: {"n": len(s), "wr": round(100 * (s > 0).mean(), 1) if len(s) else 0.0,
                       "exp": round(s.mean(), 2) if len(s) else 0.0}
        out[tipe] = {"minggu": f(mg), "sebelum": f(sb)}
    return out


def _menurun(live: dict | None, bt: dict) -> str:
    """Alasan menurun (string) atau '' kalau tidak menurun."""
    if live and live["minggu"]["n"] >= 5:
        mg, sb = live["minggu"], live["sebelum"]
        if mg["exp"] < 0:
            return f"live minggu ini rata-rata {mg['exp']:+.2f}%/trade"
        if sb["n"] >= 10 and mg["wr"] < sb["wr"] - 10:
            return f"winrate live turun {sb['wr']}% → {mg['wr']}%"
    if bt["6b"]["n"] >= MIN_N_6B and bt["6b"]["exp"] < 0:
        return f"backtest 6 bulan negatif ({bt['6b']['exp']:+.2f}%/trade)"
    if bt["4m"]["n"] >= MIN_N_4M and bt["4m"]["exp"] < bt["6b"]["exp"] - 0.5:
        return f"4 minggu terakhir melemah ({bt['4m']['exp']:+.2f}% vs {bt['6b']['exp']:+.2f}% rata-rata 6 bulan)"
    return ""


def _layak(m: dict) -> bool:
    return (m["6b"]["n"] >= MIN_N_6B and m["4m"]["n"] >= MIN_N_4M
            and m["6b"]["exp"] > 0 and m["4m"]["exp"] > 0)


def _baru_saja_ganti(aktif: dict, kategori: str, today: str) -> bool:
    for r in reversed(aktif.get("riwayat", [])):
        if r["kategori"] == kategori:
            return (pd.Timestamp(today) - pd.Timestamp(r["tanggal"])).days < COOLDOWN_HARI
    return False


def putuskan(aktif: dict, bt: dict, live: dict, today: str) -> tuple[dict, list[str]]:
    baru = {**aktif, "SWING": list(aktif["SWING"]), "riwayat": list(aktif.get("riwayat", []))}
    catatan = []

    for kat, live_tipe in (("BSJP", "BSJP"), ("BPJS", "BPJS")):
        cur = aktif[kat]
        m_cur = bt[(kat, cur)]
        alasan = _menurun(live.get(live_tipe), m_cur)
        if not alasan:
            catatan.append(f"✅ <b>{kat}</b>: tetap <code>{cur}</code> (tidak menurun)")
            continue
        kandidat = sorted([(m["6b"]["exp"], nama) for (k, nama), m in bt.items()
                           if k == kat and nama != cur and _layak(m)
                           and m["6b"]["exp"] >= m_cur["6b"]["exp"] + MARGIN
                           and m["4m"]["exp"] >= m_cur["4m"]["exp"]], reverse=True)
        if not kandidat:
            catatan.append(f"⚠️ <b>{kat}</b>: <code>{cur}</code> menurun ({html.escape(alasan)}), "
                           "tapi belum ada resep lain yang terbukti lebih bagus. Tetap dipakai.")
        elif _baru_saja_ganti(aktif, kat, today):
            catatan.append(f"⚠️ <b>{kat}</b>: menurun, kandidat <code>{kandidat[0][1]}</code>, "
                           "tapi baru diganti <2 minggu lalu. Ditunggu dulu.")
        elif not config.AUTO_SWITCH:
            catatan.append(f"💡 <b>{kat}</b>: <code>{cur}</code> menurun ({html.escape(alasan)}). "
                           f"Usulan: <code>{kandidat[0][1]}</code> (AUTO_SWITCH mati).")
        else:
            ke = kandidat[0][1]
            baru[kat] = ke
            baru["riwayat"].append({"tanggal": today, "kategori": kat, "dari": cur, "ke": ke, "alasan": alasan})
            catatan.append(f"🔄 <b>{kat}</b>: diganti <code>{cur}</code> → <code>{ke}</code>. "
                           f"Alasan: {html.escape(alasan)}.")

    # Swing: pilih ulang himpunan tipe aktif kalau keseluruhan swing menurun
    swing_live = {"minggu": {"n": 0, "wr": 0, "exp": 0}, "sebelum": {"n": 0, "wr": 0, "exp": 0}}
    for t in aktif["SWING"]:
        if t in live:
            for k in ("minggu", "sebelum"):
                a, b = swing_live[k], live[t][k]
                n = a["n"] + b["n"]
                if n:
                    a["exp"] = round((a["exp"] * a["n"] + b["exp"] * b["n"]) / n, 2)
                    a["wr"] = round((a["wr"] * a["n"] + b["wr"] * b["n"]) / n, 1)
                    a["n"] = n
    gab = {"6b": {"n": 0, "exp": 0.0}, "4m": {"n": 0, "exp": 0.0}}
    for t in aktif["SWING"]:
        for w in ("6b", "4m"):
            m = bt[("SWING", t)][w]
            n = gab[w]["n"] + m["n"]
            if n:
                gab[w]["exp"] = (gab[w]["exp"] * gab[w]["n"] + m["exp"] * m["n"]) / n
                gab[w]["n"] = n
    alasan = _menurun(swing_live, gab)
    pilihan = [t for _, t in sorted(((bt[("SWING", t)]["6b"]["exp"], t) for t in recipes.SWING_SEMUA
                                     if _layak(bt[("SWING", t)])), reverse=True)][:6]
    if not alasan:
        catatan.append("✅ <b>Swing</b>: tetap " + ", ".join(f"<code>{t}</code>" for t in aktif["SWING"]))
    elif len(pilihan) < 2 or set(pilihan) == set(aktif["SWING"]):
        catatan.append(f"⚠️ <b>Swing</b> menurun ({html.escape(alasan)}), belum ada susunan yang lebih bagus.")
    elif _baru_saja_ganti(aktif, "SWING", today):
        catatan.append("⚠️ <b>Swing</b> menurun, tapi baru diganti <2 minggu lalu. Ditunggu dulu.")
    elif not config.AUTO_SWITCH:
        catatan.append(f"💡 <b>Swing</b> menurun ({html.escape(alasan)}). Usulan: " + ", ".join(pilihan))
    else:
        baru["SWING"] = pilihan
        baru["riwayat"].append({"tanggal": today, "kategori": "SWING", "dari": aktif["SWING"],
                                "ke": pilihan, "alasan": alasan})
        keluar = [t for t in aktif["SWING"] if t not in pilihan]
        masuk = [t for t in pilihan if t not in aktif["SWING"]]
        catatan.append(f"🔄 <b>Swing</b> disusun ulang ({html.escape(alasan)}). "
                       f"Masuk: {', '.join(masuk) or '-'} · Keluar: {', '.join(keluar) or '-'}")
    baru["riwayat"] = baru["riwayat"][-30:]
    return baru, catatan


def _baris(nama, m, aktif):
    tanda = "▶️" if aktif else "  "
    return (f"{tanda} <code>{nama}</code> 6bln: {m['6b']['n']} trade, WR {m['6b']['wr']}%, "
            f"{m['6b']['exp']:+.2f}% · 4mgg: {m['4m']['n']}, WR {m['4m']['wr']}%, {m['4m']['exp']:+.2f}%")


def laporan(aktif, baru, bt, live, catatan, today, batas_4m, n_saham) -> str:
    p = [f"📋 <b>Evaluasi mingguan</b> · {today}",
         f"Backtest {config.BT_HARI} hari bursa di {n_saham} saham terlikuid, sudah dipotong fee "
         f"{config.FEE_PCT}%/trade. 4 minggu = sinyal sejak {batas_4m}."]
    p.append("<b>━━ Keputusan ━━</b>\n" + "\n".join(catatan))

    if live:
        rows = []
        for t, v in sorted(live.items()):
            mg, sb = v["minggu"], v["sebelum"]
            if mg["n"] or sb["n"]:
                rows.append(f"• {t}: minggu ini {mg['n']} trade, WR {mg['wr']}%, {mg['exp']:+.2f}% · "
                            f"4 minggu sebelumnya {sb['n']}, WR {sb['wr']}%, {sb['exp']:+.2f}%")
        p.append("<b>━━ Hasil live (bersih fee) ━━</b>\n" + ("\n".join(rows) or "Belum ada trade yang selesai."))
    else:
        p.append("<b>━━ Hasil live ━━</b>\nBelum ada trade yang selesai. Keputusan minggu ini memakai backtest.")

    for kat, judul in (("BSJP", "BSJP"), ("BPJS", "BPJS malam")):
        rows = sorted(((m["6b"]["exp"], nama, m) for (k, nama), m in bt.items() if k == kat), reverse=True)
        p.append(f"<b>━━ Backtest {judul} ━━</b>\n" +
                 "\n".join(_baris(nama, m, nama == baru[kat]) for _, nama, m in rows))
    rows = sorted(((m["6b"]["exp"], t, m) for (k, t), m in bt.items() if k == "SWING"), reverse=True)
    p.append("<b>━━ Backtest swing ━━</b>\n" + "\n".join(_baris(t, m, t in baru["SWING"]) for _, t, m in rows))
    p.append("<i>▶️ = resep aktif minggu depan. WR = winrate. Angka % = rata-rata untung/rugi bersih per trade. "
             "Backtest bukan jaminan hasil ke depan.</i>")
    return "\n\n".join(p)


def run():
    today = (datetime.now(timezone.utc) + timedelta(hours=7)).date().isoformat()
    aktif = strategi.load()
    cache = data.fetch_many(universe.scan_list())
    journal.update_open(lambda k: cache.get(k))           # tutup sinyal yang sudah selesai dulu
    bt, batas_4m, n_saham = backtest(cache)
    live = live_stats(today)
    baru, catatan = putuskan(aktif, bt, live, today)
    if baru != aktif:
        strategi.save(baru)
    telegram_send.send(laporan(aktif, baru, bt, live, catatan, today, batas_4m, n_saham))
