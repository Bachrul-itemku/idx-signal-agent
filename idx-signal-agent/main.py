"""Pemakaian:
  python main.py          scan harian + evaluasi sinyal lama (≥ 18.00 WIB hari bursa)
  python main.py stats    kirim rapor winrate ke Telegram (mis. tiap Jumat malam)
"""
import html
import sys
import config
import data
import journal
import signals
import telegram_send


def fmt(x):
    return f"{x:,.0f}".replace(",", ".") if x is not None else "-"


def render(c: dict, komentar: str = "") -> str:
    s, k = c["signal"], c["kode"]
    lines = [f"<b>{k}</b> · {signals.NAMA[s['tipe']]} · skor {s['skor']}",
             f"Close {fmt(c['close'])} ({c['chg_pct']:+.2f}%) · Vol {c['vol_ratio']}x · RSI {c['rsi']}",
             html.escape(s["alasan"])]
    if s["mode"] == "swing":
        lines.append(f"Entry ~{fmt(s['entry'])} · SL {fmt(s['sl'])} · TP1 {fmt(s['tp1'])} · RR {s['rr']}")
        lines.append(f"Lot maks (risk {config.RISK_PCT:g}% dari modal {fmt(config.MODAL_RP)}): {s['lot']}")
    elif s["mode"] == "next_day":
        lines.append(f"Target +2,5% ≈ {fmt(s['tp1'])} (dari close; hitung ulang dari harga beli)")
    if komentar:
        lines.append(f"<i>{html.escape(komentar)}</i>")
    if s.get("juga"):
        lines.append("Konfirmasi tambahan: " + ", ".join(signals.NAMA[t].split(" ", 1)[1] for t in s["juga"]))
    cek = []
    for x in signals.VERIFIKASI[s["tipe"]]:
        x = x.format(k=k)
        label, cmd = x.split(": ", 1) if ": /" in x else ("", x)
        cek.append((f"{label} " if label else "") + f"<code>{html.escape(cmd)}</code>")
    cek = " · ".join(cek)
    lines.append(f"Cek di @HQSahamIDX_bot: {cek}")
    return "\n".join(lines)


def run():
    cache, all_info, candidates, warnings = {}, {}, [], []

    def get_df(kode):
        if kode not in cache:
            cache[kode] = data.fetch(kode)
        return cache[kode]

    for kode in config.WATCHLIST:
        kode = kode.strip().upper()
        df = get_df(kode)
        if df is None:
            continue
        info = signals.analyze(kode, df)
        if not info:
            continue
        all_info[kode] = {k: v for k, v in info.items() if k != "signals"}
        for sig in info["signals"]:
            item = {**all_info[kode], "signal": sig, "id": f"{kode}:{sig['tipe']}"}
            (warnings if sig["mode"] == "warning" else candidates).append(item)

    closed = journal.update_open(get_df)       # evaluasi sinyal lama

    tanggal = next(iter(all_info.values()))["tanggal"] if all_info else "-"
    if config.SKIP_STALE:
        from datetime import datetime, timedelta, timezone
        today = (datetime.now(timezone.utc) + timedelta(hours=7)).date().isoformat()
        if tanggal != today:
            print(f"Data terbaru {tanggal}, bukan hari ini ({today}). Kemungkinan libur bursa, tidak kirim.")
            return
    header = f"📊 <b>Sinyal Saham IDX (kaidah HQSaham)</b> · {tanggal}"
    footer = ("<i>Sinyal dihitung dari harga & volume saja. Bandarmologi, asing & frekuensi "
              "wajib dicek di bot. Bahan analisa, bukan ajakan beli/jual.</i>")
    if closed:
        footer = f"🗂 {closed} sinyal lama selesai dievaluasi (lihat rapor mingguan).\n\n" + footer

    candidates.sort(key=lambda x: -x["signal"]["skor"])
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

    if picks is None:   # tanpa AI / AI gagal → ambil skor tertinggi
        picks = [{"id": c["id"], "komentar": ""} for c in candidates]
    picks = picks[:config.MAX_SIGNALS]

    # Jurnal: simpan SEMUA kandidat (termasuk yang dibuang AI) + peringatan
    chosen = {p["id"]: p["komentar"] for p in picks}
    for c in candidates:
        flag = (1 if c["id"] in chosen else 0) if ai_ran else None
        journal.save(c, flag, chosen.get(c["id"], ""))
    for w in warnings:
        journal.save(w, None)

    by_id = {c["id"]: c for c in candidates}
    # Satu saham satu kartu: sinyal swing lain di saham yang sama jadi "konfirmasi tambahan"
    swing_picks, seen = [], {}
    for p in picks:
        c = by_id[p["id"]]
        if c["signal"]["mode"] != "swing":
            continue
        if c["kode"] in seen:
            seen[c["kode"]]["signal"].setdefault("juga", []).append(c["signal"]["tipe"])
            continue
        c = {**c, "signal": dict(c["signal"])}
        seen[c["kode"]] = c
        swing_picks.append((c, p["komentar"]))
    swing = [render(c, kom) for c, kom in swing_picks]
    bpjs = [render(by_id[p["id"]], p["komentar"]) for p in picks if by_id[p["id"]]["signal"]["mode"] == "next_day"]

    parts = [header]
    if ringkasan:
        parts.append(html.escape(ringkasan))
    if swing:
        parts.append("<b>━━ Sinyal swing ━━</b>")
        parts += swing
    if bpjs:
        parts.append("<b>━━ Watchlist BPJS besok ━━</b>")
        parts += bpjs
    if warnings:
        parts.append("<b>━━ Peringatan exit (kalau sedang pegang) ━━</b>")
        parts.append("\n".join(f"🔴 <b>{w['kode']}</b> {fmt(w['close'])}: {html.escape(w['signal']['alasan'])}"
                               for w in warnings))
    if not (swing or bpjs or warnings):
        parts.append("Tidak ada sinyal hari ini." if not candidates
                     else "Ada kandidat, tapi tidak ada yang lolos tinjauan AI.")
    parts.append(footer)
    telegram_send.send("\n\n".join(parts))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        telegram_send.send(journal.stats_text())
    else:
        run()
