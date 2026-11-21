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


def render_bpjs(c: dict, komentar: str = "") -> str:
    s, k = c["signal"], c["kode"]
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
    if s["tipe"] == "BSJP":
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
    all_info, swing_c, bpjs_c, warnings = {}, [], [], []
    for kode, df in cache.items():
        try:
            info = signals.analyze(kode, df, aktif)
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
                bpjs_c.append(item)
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
    bpjs_c = [c for c in bpjs_c if c["tanggal"] == tanggal]

    rank = lambda x: (-x["signal"]["skor"], -x["value_miliar"])
    swing_c.sort(key=rank)
    bpjs_c.sort(key=rank)
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
    if picks is None:
        picks = [{"id": c["id"], "komentar": ""} for c in swing_c[:config.MAX_SIGNALS * 2]]
        picks += [{"id": c["id"], "komentar": ""} for c in bpjs_c[:config.MAX_PER_LIST]]

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
            if len(bpjs_cards) < config.MAX_PER_LIST:
                bpjs_cards.append(render_bpjs(c, p["komentar"]))
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
    parts += bpjs_cards or ["Tidak ada kandidat BPJS."]
    parts.append(f"<b>━━ Sinyal swing ({len(swing_cards)}) ━━</b>")
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
    cache = load_data(period="3mo")
    if uji:
        today = max(str(df.index[-1].date()) for df in cache.values())
        frac = 1.0 if kind == "bsjp" else signals.session_fraction(wib.replace(hour=10, minute=0))
    if not any(str(df.index[-1].date()) == today for df in cache.values()):
        print("Belum ada data hari ini (libur bursa / data belum masuk), tidak kirim.")
        return

    semalam = journal.bpjs_semalam(today) if kind == "bpjs" else set()
    resep_bsjp = strategi.load()["BSJP"]
    hasil = []
    for kode, df in cache.items():
        if str(df.index[-1].date()) != today:
            continue
        try:
            r = signals.bpjs_live(kode, df, frac, semalam) if kind == "bpjs" else signals.bsjp(kode, df, frac, resep_bsjp)
        except Exception as e:
            print(f"[{kind}] {kode} dilewati: {e}")
            continue
        if r:
            hasil.append(r)

    hasil.sort(key=lambda x: (-x["signal"]["skor"], -x["value_miliar"]))
    baru = []
    for r in hasil:                                     # simpan & kirim hanya yang baru, maks 10 per pesan
        if len(baru) >= config.MAX_PER_LIST:
            break
        if uji or journal.save(r, None):
            baru.append(r)
    print(f"[{kind}] {len(hasil)} kandidat, {len(baru)} baru")
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


def run_auto():
    """Dipanggil jadwal GitHub; pilih tugas sesuai jam WIB (jadwal GitHub bisa molor)."""
    wib = now_wib()
    m = wib.hour * 60 + wib.minute
    if wib.weekday() >= 5:
        print("Akhir pekan, tidak ada tugas.")
    elif 9 * 60 <= m <= 11 * 60 + 10:
        run_live("bpjs")
    elif 14 * 60 + 55 <= m <= 15 * 60 + 50:
        run_live("bsjp")
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
    elif cmd in ("bsjp-uji", "bpjs-uji"):
        run_live(cmd.split("-")[0], uji=True)
    elif cmd == "evaluasi":
        import evaluasi
        evaluasi.run()
    elif cmd == "auto":
        run_auto()
    else:
        run_scan()
