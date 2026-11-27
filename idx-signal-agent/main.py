"""Pemakaian:
  python main.py          scan malam (≥ 18.00 WIB): sinyal swing + daftar BPJS besok + peringatan exit
  python main.py bpjs     pantau BPJS live (09.00–11.00 WIB), kirim kandidat baru
  python main.py bsjp     pantau BSJP live (15.00–15.50 WIB), kirim kandidat baru
  python main.py auto     pilih tugas otomatis sesuai jam WIB (dipakai jadwal GitHub)
  python main.py evaluasi evaluasi mingguan: nilai performa, backtest resep lain, ganti otomatis
  python main.py stats    rapor winrate (mis. tiap Jumat malam)
"""
import html
import sys
from datetime import datetime, timedelta, timezone
import config
import data
import journal
import aturan
import fitur_bot as fb
import signals
import strategi
import telegram_send
import universe

FOOTER = ("<i>Dihitung dari harga & volume (Yahoo, telat ±15 menit). Bandarmologi, asing, "
          "frekuensi & bid-offer wajib dicek di bot. Bahan analisa, bukan ajakan beli/jual.</i>")


def now_wib():
    return datetime.now(timezone.utc) + timedelta(hours=7)


def dec(x, n=1):
    """Desimal gaya Indonesia: 12.5 -> 12,5"""
    return f"{x:.{n}f}".replace(".", ",")


def fmt(x):
    return f"{x:,.0f}".replace(",", ".") if x is not None else "-"


def cek_bot(tipe, k):
    out = []
    for x in signals.VERIFIKASI[tipe]:
        x = x.format(k=k)
        label, cmd = x.split(": ", 1) if ": /" in x else ("", x)
        out.append((f"{label} " if label else "") + f"<code>{html.escape(cmd)}</code>")
    return "Cek di bot: " + " · ".join(out)


def render_swing(c: dict, komentar: str = "") -> str:
    s, k = c["signal"], c["kode"]
    lines = [f"<b>{k}</b> · {signals.NAMA[s['tipe']]} · skor {s['skor']}",
             f"Close {fmt(c['close'])} ({'+' if c['chg_pct'] >= 0 else ''}{dec(c['chg_pct'], 2)}%) · Nilai {dec(c['value_miliar'])} M · Vol {dec(c['vol_ratio'])}x · RSI {c['rsi']}",
             html.escape(s["alasan"]),
             f"Entry ~{fmt(s['entry'])} · SL {fmt(s['sl'])} · TP1 {fmt(s['tp1'])} · RR {s['rr']}",
             f"Lot maks (risk {config.RISK_PCT:g}% dari modal {fmt(config.MODAL_RP)}): {s['lot']}"]
    if s.get("juga"):
        lines.append("Konfirmasi tambahan: " + ", ".join(signals.NAMA[t].split(" ", 1)[1] for t in s["juga"]))
    if komentar:
        lines.append(f"<i>{html.escape(komentar)}</i>")
    lines.append(cek_bot(s["tipe"], k))
    return "\n".join(lines)


def render_dip_list(items: list) -> str:
    """BPJS: aturan per lapis sekali, lalu satu baris per saham (keranjang)."""
    rows = []
    for c in items:
        bintang = "⭐ " if c["signal"].get("lapis") == "plus" else ""
        rows.append(f"🩸 {bintang}<b>{c['kode']}</b> close {fmt(c['close'])} ({dec(c['chg_pct'], 1)}%, "
                    f"5 hari {dec(c.get('ret5', 0), 1)}%) · nilai {dec(c['value_miliar'])} M")
    lapis = []
    for r in aturan.rules("BPJS"):
        st = r.get("stat", {})
        angka = (f" (riset: menang {st['wr_pilih']:.0%}, rata-rata {st['ex_pilih']:+.2f}%)".replace(".", ",")
                 if st else "")
        lapis.append(f"{'⭐ ' if r['lapis'] == 'plus' else '• '}<b>{r['lapis']}</b>: "
                     f"{html.escape(fb.label(r['syarat']))}{angka}")
    return "\n".join([
        "🟢 <b>Beli besok di pembukaan (09.00)</b>, harga open berapa pun.",
        "🎯 <b>Jual besok di penutupan</b> (pre-closing 15.50–16.00 / post-trading). Jangan cut di tengah hari.",
        "🧺 Untungnya dari <b>keranjang</b>: beli beberapa saham sekaligus dengan porsi kecil. "
        "Diurutkan dari lapis tertinggi, lalu yang paling jatuh 5 hari.",
        "Aturan aktif (hasil riset otomatis terbaru):", *lapis, "", *rows,
        "", "Cek di bot (contoh): " + " · ".join(f"<code>/BOR {c['kode']}</code>" for c in items[:3]),
    ])


def render_bpjs(c: dict, komentar: str = "") -> str:
    s, k = c["signal"], c["kode"]
    if (s.get("resep") or "").startswith("BPJS_DIP"):
        lines = [f"🩸 <b>{k}</b> · buy the dip · close {fmt(c['close'])} "
                 f"({'+' if c['chg_pct'] >= 0 else ''}{dec(c['chg_pct'], 2)}%) · nilai {dec(c['value_miliar'])} M",
                 html.escape(s["alasan"]),
                 "🟢 <b>Masuk besok di pembukaan (09.00)</b>, harga open berapa pun",
                 "🎯 <b>Keluar besok di penutupan</b> (pre-closing 15.50–16.00 / post-trading), untung atau rugi",
                 "📊 Riset: menang ±61% (±65% saat IHSG turun >2%), rata-rata +2,5% bersih per trade. "
                 "Untungnya dari KERANJANG: beli beberapa saham dengan porsi kecil, jangan cut di tengah hari."]
        if komentar:
            lines.append(f"<i>{html.escape(komentar)}</i>")
        lines.append(cek_bot("BPJS", k))
        return "\n".join(lines)
    lines = [f"☀️ <b>{k}</b> · skor {s['skor']} · close {fmt(c['close'])} ({'+' if c['chg_pct'] >= 0 else ''}{dec(c['chg_pct'], 2)}%) · nilai {dec(c['value_miliar'])} M · vol {dec(c['vol_ratio'])}x",
             f"🟢 <b>Masuk besok 09.15–09.30</b> di {fmt(s['beli_bawah'])}–{fmt(s['beli_atas'])}, "
             f"hanya jika open ≥ {fmt(s['beli_bawah'])} dan ≤ {fmt(s['open_maks'])} serta harga bertahan di atas open",
             f"🎯 <b>Keluar</b>: jual sebagian di {fmt(s['tp1'])} (+2,5%), sisanya target {fmt(s['tp2'])} (+4%) "
             f"atau jual semua paling lambat <b>15.30–15.45</b>",
             f"🛑 <b>Cut</b>: turun di bawah low 15 menit pertama, batas keras {fmt(s['sl'])} (−2%)"]
    if komentar:
        lines.append(f"<i>{html.escape(komentar)}</i>")
    lines.append(cek_bot("BPJS", k))
    return "\n".join(lines)


def render_live(c: dict) -> str:
    s, k = c["signal"], c["kode"]
    head = (f"<b>{k}</b> · skor {s['skor']} · harga {fmt(c['close'])} "
            f"({'+' if c['chg_pct'] >= 0 else ''}{dec(c['chg_pct'], 2)}%) · nilai {dec(c['value_miliar'])} M")
    if s["tipe"] == "BSJP" and (s.get("resep") or "").startswith("AUTO_BSJP"):
        label = {"plus": "⭐⭐ PLUS · ", "utama": "⭐ UTAMA · ", "cadangan": "▫️ CADANGAN · "}.get(s.get("lapis"), "")
        return "\n".join([
            label + head, html.escape(s["alasan"]),
            f"🟢 <b>Beli SORE INI s.d. 15.49 / post-trading</b> di {fmt(s['beli_bawah'])}–{fmt(s['beli_atas'])}; "
            f"jangan kejar di atas {fmt(s['jangan_di_atas'])}",
            "🎯 <b>Jual BESOK PAGI di pembukaan (09.00, harga open)</b>, untung atau rugi.",
            aturan.teks_stat(s.get("stat", {})), cek_bot("BSJP", k)])
    if s["tipe"] == "BSJP" and (s.get("resep") or "").startswith("BSJP_MOMBB"):
        lapis = s.get("lapis", "utama")
        label, riset = {
            "plus": ("⭐⭐ UTAMA+ · ", "📊 Riset: menang ±76%, rata-rata +0,8% bersih per trade (terbaik)."),
            "utama": ("⭐ UTAMA · ", "📊 Riset: menang ±68%, rata-rata +0,6% bersih per trade."),
            "cadangan": ("▫️ CADANGAN · ", "📊 Riset: menang ±64%, rata-rata +0,6% bersih per trade."),
        }.get(lapis, ("", ""))
        head = label + head
        rencana = [
            f"🟢 <b>Beli SORE INI s.d. 15.49 / post-trading</b> di {fmt(s['beli_bawah'])}–{fmt(s['beli_atas'])}; "
            f"jangan kejar di atas {fmt(s['jangan_di_atas'])}",
            "🎯 <b>Jual BESOK PAGI di pembukaan (09.00, harga open)</b>, untung atau rugi.",
            riset,
        ]
    elif s["tipe"] == "BSJP":
        rencana = [
            f"🟢 <b>Masuk sekarang s.d. 15.49</b> di {fmt(s['beli_bawah'])}–{fmt(s['beli_atas'])}; "
            f"jangan kejar di atas {fmt(s['jangan_di_atas'])}",
            f"🎯 <b>Keluar besok 09.00–09.30</b> di {fmt(s['tp1'])} (+2%) atau {fmt(s['tp2'])} (+3%)",
            f"🛑 <b>Cut</b>: open besok di bawah harga beli & tak pulih 15–30 menit, batas keras {fmt(s['sl'])}",
        ]
    else:
        rencana = [
            f"🟢 <b>Masuk sekarang</b> di {fmt(s['beli_bawah'])}–{fmt(s['beli_atas'])}; "
            f"jangan kejar di atas {fmt(s['jangan_di_atas'])}",
            f"🎯 <b>Keluar hari ini</b>: jual sebagian di {fmt(s['tp1'])} (+2,5%), sisanya {fmt(s['tp2'])} (+4%) "
            f"atau jual semua paling lambat <b>15.30–15.45</b>",
            f"🛑 <b>Cut</b>: turun di bawah open, yaitu ≤ {fmt(s['sl'])}",
        ]
    return "\n".join([head, html.escape(s["alasan"]), *rencana, cek_bot(s["tipe"], k)])


def load_data(period=None):
    kodes = universe.scan_list()
    print(f"[main] memindai {len(kodes)} saham ({config.UNIVERSE})")
    return data.fetch_many(kodes, period=period)


def run_scan():
    cache = load_data()

    def get_df(kode):
        if kode not in cache:
            cache[kode] = data.fetch(kode)
        return cache[kode]

    aktif = strategi.load()
    pasar_all = data.pasar_series(cache, period="6mo")
    hari_akhir = max(str(df.index[-1].date()) for df in cache.values()) if cache else ""
    pasar = pasar_all.get(hari_akhir, {})
    print(f"[main] pasar {hari_akhir}: {pasar}")
    all_info, swing_c, bpjs_c, warnings = {}, [], [], []
    for kode, df in cache.items():
        try:
            info = signals.analyze(kode, df, aktif, pasar)
        except Exception as e:
            print(f"[signals] {kode} dilewati: {e}")
            continue
        if not info:
            continue
        all_info[kode] = {k: v for k, v in info.items() if k != "signals"}
        for sig in info["signals"]:
            item = {**all_info[kode], "signal": sig, "id": f"{kode}:{sig['tipe']}"}
            if sig["mode"] == "warning":
                if kode in config.WATCHLIST:           # peringatan exit hanya untuk yang dipegang
                    warnings.append(item)
            elif sig["mode"] == "next_day":
                continue                               # BPJS kini dari aturan riset otomatis (di bawah)
            else:
                swing_c.append(item)

    closed = journal.update_open(get_df)

    dates = sorted({v["tanggal"] for v in all_info.values()})
    tanggal = dates[-1] if dates else "-"
    if config.SKIP_STALE and tanggal != now_wib().date().isoformat():
        print(f"Data terbaru {tanggal}, bukan hari ini. Kemungkinan libur bursa, tidak kirim.")
        return
    # Abaikan saham yang datanya tidak update (suspend dsb.)
    swing_c = [c for c in swing_c if c["tanggal"] == tanggal]
    # BPJS (beli open besok, jual close besok) dari aturan hasil riset otomatis
    try:
        Fh = aturan.fitur_hari_ini(cache, data.fetch_symbol("^JKSE", "1y"), tanggal)
        bpjs_c, _ = aturan.sinyal(Fh, "BPJS")
        for c in bpjs_c:
            c["id"] = f"{c['kode']}:BPJS"
    except Exception as e:
        print(f"[bpjs] aturan gagal: {e}")
        bpjs_c = []

    rank = lambda x: (-x["signal"]["skor"], -x["value_miliar"])
    swing_c.sort(key=rank)
    bpjs_c.sort(key=lambda x: (-x["signal"]["skor"], x.get("ret5", 0)))   # lapis tertinggi, lalu paling jatuh
    candidates = (swing_c + bpjs_c)[:config.MAX_AI_CANDIDATES]

    picks, ringkasan, ai_ran = None, "", False
    if candidates and config.USE_AI and config.ANTHROPIC_API_KEY:
        try:
            import agent
            result = agent.review(candidates, all_info)
            if result:
                ai_ran = True
                ringkasan = result.get("ringkasan", "")
                valid = {c["id"] for c in candidates}
                picks = [p for p in result.get("picks", []) if p["id"] in valid]   # guardrail
        except Exception as e:
            print(f"[agent] gagal, pakai sinyal mentah: {e}")
    dip = True                                   # BPJS ditampilkan sebagai daftar keranjang
    maks_bpjs = 20
    if picks is None:
        picks = [{"id": c["id"], "komentar": ""} for c in swing_c[:config.MAX_SIGNALS * 2]]
        picks += [{"id": c["id"], "komentar": ""} for c in bpjs_c[:maks_bpjs]]

    chosen = {p["id"]: p["komentar"] for p in picks}
    for c in swing_c + bpjs_c:
        flag = (1 if c["id"] in chosen else 0) if ai_ran else None
        journal.save(c, flag, chosen.get(c["id"], ""))
    for w in warnings:
        journal.save(w, None)

    by_id = {c["id"]: c for c in swing_c + bpjs_c}
    swing_cards, seen, bpjs_cards = [], {}, []
    for p in picks:
        c = by_id[p["id"]]
        if c["signal"]["mode"] == "next_day":
            if len(bpjs_cards) < maks_bpjs:
                bpjs_cards.append(c if dip else render_bpjs(c, p["komentar"]))
            continue
        if c["kode"] in seen:                           # satu saham satu kartu
            seen[c["kode"]]["signal"].setdefault("juga", []).append(c["signal"]["tipe"])
            continue
        if len(seen) >= config.MAX_SIGNALS:
            continue
        c = {**c, "signal": dict(c["signal"])}
        seen[c["kode"]] = c
        swing_cards.append((c, p["komentar"]))
    swing_cards = [render_swing(c, k) for c, k in swing_cards]

    parts = [f"📊 <b>Sinyal Saham IDX (kaidah HQSaham)</b> · {tanggal}\n"
             f"Dipindai {len(all_info)} saham likuid dari {len(cache)} saham"]
    if ringkasan:
        parts.append(html.escape(ringkasan))
    parts.append(f"<b>━━ ☀️ Daftar BPJS besok ({len(bpjs_cards)}) ━━</b>")
    if dip and bpjs_cards:
        parts.append(render_dip_list(bpjs_cards))
    else:
        parts += bpjs_cards or ["Tidak ada kandidat BPJS. Syarat aktif:\n" + "\n".join(
            f"• {r['lapis']}: {html.escape(fb.label(r['syarat']))}" for r in aturan.rules("BPJS"))]
    parts.append(f"<b>━━ Sinyal swing ({len(swing_cards)}) ━━</b>")
    if pasar.get("ihsg_up50") is False:
        parts.append("⏸ Swing ditahan: IHSG di bawah MA50. Riset 2 tahun: swing rugi saat pasar turun.")
    else:
        parts += swing_cards or ["Tidak ada sinyal swing."]
    if warnings:
        parts.append("<b>━━ 🔴 Peringatan exit (saham di WATCHLIST) ━━</b>")
        parts.append("\n".join(f"🔴 <b>{w['kode']}</b> {fmt(w['close'])}: {html.escape(w['signal']['alasan'])}"
                               for w in warnings))
    if closed:
        parts.append(f"🗂 {closed} sinyal lama selesai dievaluasi (lihat rapor mingguan).")
    parts.append(FOOTER)
    telegram_send.send("\n\n".join(parts))


def run_live(kind: str, uji: bool = False):
    """Pemantauan berkala: kind = 'bpjs' (09.00–11.00) atau 'bsjp' (15.00–15.50).
    Hanya mengirim saham yang BARU muncul hari itu.
    uji=True: pakai hari bursa terakhir (untuk mencoba di luar jam bursa), tidak dicatat."""
    wib = now_wib()
    today = wib.date().isoformat()
    frac = signals.session_fraction(wib - timedelta(minutes=15))     # data Yahoo telat ±15 menit
    cache = load_data(period="1y" if kind == "bsjp" else "3mo")
    if uji:
        today = max(str(df.index[-1].date()) for df in cache.values())
        frac = 1.0 if kind == "bsjp" else signals.session_fraction(wib.replace(hour=10, minute=0))
    if not any(str(df.index[-1].date()) == today for df in cache.values()):
        print("Belum ada data hari ini (libur bursa / data belum masuk), tidak kirim.")
        if not uji:
            journal.log_run(today, kind, f"{wib:%H.%M}", len(cache), 0, 0, 0, {})
        return

    semalam = journal.bpjs_semalam(today) if kind == "bpjs" else set()
    hasil, gagal, n_hari_ini = [], {}, 0
    if kind == "bsjp":                      # aturan hasil riset otomatis (strategi.json)
        n_hari_ini = sum(1 for df in cache.values() if str(df.index[-1].date()) == today)
        Fh = aturan.fitur_hari_ini(cache, data.fetch_symbol("^JKSE", "1y"), today, frac)
        hasil, gagal = aturan.sinyal(Fh, "BSJP")
    for kode, df in (cache.items() if kind == "bpjs" else []):
        if str(df.index[-1].date()) != today:
            continue
        n_hari_ini += 1
        try:
            r = signals.bpjs_live(kode, df, frac, semalam)
        except Exception as e:
            print(f"[{kind}] {kode} dilewati: {e}")
            continue
        if r:
            hasil.append(r)
    print(f"[{kind}] {n_hari_ini}/{len(cache)} saham punya candle hari ini; gagal syarat: {gagal}")

    hasil.sort(key=lambda x: (-x["signal"]["skor"], -x["value_miliar"]))
    baru = []
    for r in hasil:                                     # simpan & kirim hanya yang baru, maks 10 per pesan
        if len(baru) >= config.MAX_PER_LIST:
            break
        if uji or journal.save(r, None):
            baru.append(r)
    print(f"[{kind}] {len(hasil)} kandidat, {len(baru)} baru")
    if not uji:
        journal.log_run(today, kind, f"{wib:%H.%M}", len(cache), n_hari_ini, len(hasil), len(baru), gagal)
    if not baru:
        return                                          # tidak ada yang baru: diam saja

    judul = "⚡ <b>BPJS live</b>" if kind == "bpjs" else "🌙 <b>BSJP live</b>"
    if uji:
        judul = "🧪 UJI · " + judul
    jam = "data penutupan (mode uji)" if uji else f"data ±{(wib - timedelta(minutes=15)):%H.%M} WIB"
    parts = [f"{judul} · {today} · {jam} · {len(baru)} saham baru",
             "Harga dari data yang telat ±15 menit. Cek harga live & antrean sebelum beli."]
    if kind == "bsjp" and wib.weekday() == 4:
        parts.append("⚠️ Hari Jumat: komunitas HQ menyarankan hindari BSJP (risiko libur akhir pekan).")
    parts += [render_live(r) for r in baru]
    parts.append(FOOTER)
    telegram_send.send("\n\n".join(parts))


LABEL_GAGAL = {
    "tidak_hijau": "candle tidak hijau (close ≤ open)",
    "di_bawah_ma20": "di bawah MA20",
    "naik_kurang_2": "naik < 2%",
    "naik_lebih_15": "naik > 15%",
    "volume_kurang": "volume belum di atas normal",
    "nilai_kurang": "nilai transaksi belum ≥ 5 M",
    "tidak_likuid": "tidak likuid / harga gocap",
    "di_bawah_bb_atas": "belum menembus upper Bollinger",
    "naik_kurang_4": "naik ≤ 4%",
    "rata_nilai_kurang_50": "rata nilai transaksi 20 hari < 50 M",
    "harga_luar_200_1000": "harga di luar 200–1.000",
}


def ringkasan(kind: str):
    """Laporan harian yang SELALU dikirim: berapa kali dicek, hasilnya, dan penyebab kalau kosong."""
    wib = now_wib()
    today = wib.date().isoformat()
    if journal.runs_hari_ini(today, f"ringkasan-{kind}"):
        print(f"Ringkasan {kind} hari ini sudah dikirim.")
        return
    runs = journal.runs_hari_ini(today, kind)
    if not runs and kind == "bsjp" and wib.hour * 60 + wib.minute <= 16 * 60 + 12:
        run_live("bsjp")                              # belum pernah dicek: cek sekarang (post-trading)
        runs = journal.runs_hari_ini(today, kind)
    tipe = "BSJP" if kind == "bsjp" else "BPJS_LIVE"
    terkirim = journal.sinyal_hari_ini(today, tipe)
    judul = "🌙 <b>Ringkasan BSJP</b>" if kind == "bsjp" else "⚡ <b>Ringkasan BPJS live</b>"
    p = [f"{judul} · {today}"]
    if not runs:
        p.append("❗ Hari ini <b>tidak ada pengecekan yang berjalan</b> di jendela waktunya. "
                 "Penyebab: jadwal GitHub terlambat/terlewat. Bukan berarti tidak ada sinyal.")
    else:
        jam = ", ".join(r["jam"] for r in runs)
        p.append(f"Dicek {len(runs)} kali (jam {jam}).")
        if terkirim:
            p.append(f"✅ {len(terkirim)} saham sudah dikirim: " + ", ".join(terkirim))
        elif max(r["n_hari_ini"] for r in runs) == 0:
            p.append("❗ Data candle hari ini tidak tersedia dari Yahoo saat dicek, jadi tidak bisa dinilai.")
        else:
            last = runs[-1]
            p.append(f"Tidak ada saham yang lolos syarat dari {last['n_hari_ini']} saham.")
            if last["gagal"]:
                top = sorted(last["gagal"].items(), key=lambda x: -x[1])[:4]
                p.append("Syarat yang paling sering gagal (pengecekan terakhir):\n" + "\n".join(
                    f"• {html.escape(LABEL_GAGAL.get(k, k))}: {v} saham" for k, v in top))
            p.append("Artinya hari ini tidak ada setup yang sesuai resep. Ini normal di hari lesu.")
    if telegram_send.send("\n\n".join(p)):
        journal.log_run(today, f"ringkasan-{kind}", f"{wib:%H.%M}", 0, 0, 0, 0, {})


def loop_live(kind: str):
    """Satu run panjang: cek tiap ±10 menit sampai jendela habis, lalu kirim ringkasan.
    Tidak bergantung pada jadwal GitHub yang sering molor."""
    import time as _t
    mulai, akhir = (14 * 60 + 45, 15 * 60 + 58) if kind == "bsjp" else (9 * 60 + 2, 11 * 60 + 5)
    if journal.runs_hari_ini(now_wib().date().isoformat(), f"ringkasan-{kind}"):
        print(f"Loop {kind} hari ini sudah selesai.")
        return
    while True:
        wib = now_wib()
        m = wib.hour * 60 + wib.minute
        if m > akhir:
            break
        if m >= mulai:
            t0 = _t.time()
            try:
                run_live(kind)
            except Exception as e:
                print(f"[loop] {kind} error: {e}")
            tunggu = max(60, 600 - (_t.time() - t0))           # ±10 menit per putaran
        else:
            tunggu = min(600, (mulai - m) * 60)
        sisa = (akhir - (now_wib().hour * 60 + now_wib().minute)) * 60
        if sisa <= 0:
            break
        _t.sleep(min(tunggu, max(sisa, 60)))
    ringkasan(kind)


def run_auto():
    """Dipanggil jadwal GitHub; pilih tugas sesuai jam WIB (jadwal GitHub bisa molor)."""
    wib = now_wib()
    m = wib.hour * 60 + wib.minute
    if wib.weekday() >= 5:
        print("Akhir pekan, tidak ada tugas.")
    elif 9 * 60 <= m <= 11 * 60 + 10:
        run_live("bpjs")
    elif 11 * 60 + 10 < m <= 12 * 60:
        ringkasan("bpjs")
    elif 13 * 60 + 30 <= m <= 15 * 60 + 58:
        loop_live("bsjp")
    elif 15 * 60 + 58 < m <= 17 * 60 + 15:
        ringkasan("bsjp")
    elif m >= 17 * 60 + 30:
        run_scan()
    else:
        print(f"Jam {wib:%H.%M} WIB di luar jendela tugas, dilewati.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if cmd == "stats":
        telegram_send.send(journal.stats_text())
    elif cmd in ("bsjp", "bpjs"):
        run_live(cmd)
    elif cmd in ("loop-bsjp", "loop-bpjs"):
        loop_live(cmd.split("-")[1])
    elif cmd in ("ringkasan-bsjp", "ringkasan-bpjs"):
        ringkasan(cmd.split("-")[1])
    elif cmd in ("bsjp-uji", "bpjs-uji"):
        run_live(cmd.split("-")[0], uji=True)
    elif cmd == "riset":                    # kirim laporan riset (laporan_riset.txt) ke Telegram
        import os
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "laporan_riset.txt")) as fh:
            telegram_send.send(fh.read().strip())
    elif cmd == "riset-otomatis":
        import riset_otomatis
        riset_otomatis.run()
    elif cmd == "mingguan":                 # Sabtu: riset BSJP/BPJS lalu evaluasi swing, data sama
        import evaluasi, riset_otomatis
        cache3 = data.fetch_many(universe.load(), period="3y")
        riset_otomatis.run(cache=cache3, ihsg=data.fetch_symbol("^JKSE", "3y"))
        evaluasi.run(cache=cache3)
    elif cmd == "evaluasi":
        import evaluasi
        evaluasi.run()
    elif cmd == "auto":
        run_auto()
    else:
        run_scan()
