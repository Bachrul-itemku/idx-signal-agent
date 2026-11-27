"""Riset otomatis mingguan untuk BSJP & BPJS: cari kombinasi syarat terbaik di data 3 tahun terbaru,
lalu pakai yang terbukti paling bagus.

Cara memilih (anti "kebetulan"):
1. Data dibagi 5 periode berurutan. Periode 1–4 untuk MEMILIH, periode 5 (±3,5 bulan terakhir)
   untuk KONFIRMASI dan tidak dipakai saat memilih.
2. Lolos pilih: ≥50 trade, menang ≥55%, rata-rata ≥ +0,3% bersih fee, positif di ≥3 dari 4 periode.
3. Lolos konfirmasi: di periode terbaru tetap positif & menang ≥50%.
4. Skor memakai penyusutan statistik (sampel kecil ditarik ke 50%) + penalti aturan yang terlalu panjang.
   Per lapis (plus / utama / cadangan) dipilih skor tertinggi yang cukup sering muncul.
5. Juara lama hanya diganti kalau penantang unggul jelas (skor +2)."""
import html
import itertools
import time
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd
import data
import fitur_bot as fb
import strategi
import telegram_send
import universe

KELUARAN = {"BSJP": "bsjp_open", "BPJS": "bpjs_close"}
CAKUPAN = {"BSJP": {"plus": 0.08, "utama": 0.2, "cadangan": 0.4},     # porsi hari bursa yang ada sinyal
           "BPJS": {"plus": 0.03, "utama": 0.1}}
MARGIN = 2.0


def bangun_panel(cache: dict, ihsg) -> pd.DataFrame:
    parts = [fb.per_saham(df, k, hasil=True) for k, df in cache.items() if len(df) > 260]
    F = fb.lengkapi(pd.concat(parts, ignore_index=True), ihsg)
    return F[fb.bisa_ditransaksikan(F)].reset_index(drop=True)


class Penguji:
    def __init__(self, F: pd.DataFrame, fam: str):
        if fam == "BPJS":                                  # tidak bisa beli kalau open besok sudah ARA
            F = F[F.n_gap.notna() & (F.n_gap < 9.4)].reset_index(drop=True)
        self.F, self.fam = F, fam
        self.y = F[KELUARAN[fam]].to_numpy(float)
        dates = np.sort(F.Date.unique())
        self.n_hari = len(dates)
        edges = np.array([dates[int(len(dates) * k / 5)] for k in range(1, 5)])
        self.fold = np.searchsorted(edges, F.Date.values, side="right")
        self.day = pd.factorize(F.Date)[0]
        self.awal_hold = str(pd.Timestamp(edges[-1]).date())
        self.names = list(fb.S)
        self.B = {n: fb._b(fb.S[n][0](F)).to_numpy(bool) for n in self.names}
        self.ok = ~np.isnan(self.y)

    def stat(self, syarat) -> dict:
        m = self.ok.copy()
        for s in syarat:
            m &= self.B[s]
        idx = np.flatnonzero(m)
        y, fo = self.y[idx], self.fold[idx]
        n = np.bincount(fo, minlength=5)
        w = np.bincount(fo, weights=(y > 0).astype(float), minlength=5)
        t = np.bincount(fo, weights=y, minlength=5)
        sel = fo < 4
        ns = int(sel.sum())
        r = {"syarat": list(syarat), "n_pilih": ns,
             "wr_pilih": float((y[sel] > 0).mean()) if ns else 0.0,
             "ex_pilih": float(y[sel].mean()) if ns else 0.0,
             "n_baru": int(n[4]), "wr_baru": float(w[4] / n[4]) if n[4] else 0.0,
             "ex_baru": float(t[4] / n[4]) if n[4] else 0.0,
             "periode_positif": int(sum(1 for k in range(4) if n[k] >= 3 and t[k] > 0)),
             "cakupan": len(np.unique(self.day[idx])) / self.n_hari,
             "n_total": len(idx)}
        r["lolos_pilih"] = ns >= 50 and r["wr_pilih"] >= 0.55 and r["ex_pilih"] >= 0.3 and r["periode_positif"] >= 3
        r["lolos_baru"] = r["n_baru"] >= 5 and r["ex_baru"] > 0 and r["wr_baru"] >= 0.5
        # Penyusutan: sampel kecil ditarik ke arah menang 50% / rata-rata 0 (anti kebetulan)
        wp = (w[:4].sum() + 0.5 * 20) / (ns + 20) if ns else 0.5
        wb = (w[4] + 0.5 * 15) / (n[4] + 15)
        ep = r["ex_pilih"] * ns / (ns + 20)
        eb = r["ex_baru"] * n[4] / (n[4] + 15)
        r["skor"] = (60 * wp + 40 * wb + 5 * min(ep, eb) - 0.5 * max(0, len(syarat) - 4)) if n[4] else 0.0
        return r


def cari(P: Penguji, juara_lama: list[list[str]], batas_detik=900) -> list[dict]:
    t0 = time.time()
    names, B, ok = P.names, P.B, P.ok
    sel = P.fold < 4
    kandidat = {}

    def nilai(combo):
        key = tuple(sorted(combo))
        if key not in kandidat:
            kandidat[key] = P.stat(list(key))
        return kandidat[key]

    # Tahap 1: semua kombinasi 1–3 syarat, saring cepat di periode pilih
    lolos = []
    for k in (1, 2, 3):
        for combo in itertools.combinations(range(len(names)), k):
            m = B[names[combo[0]]] & ok & sel
            for j in combo[1:]:
                m = m & B[names[j]]
            c = int(m.sum())
            if c < 50:
                continue
            yv = P.y[m]
            if (yv > 0).mean() >= 0.55 and yv.mean() >= 0.3:
                lolos.append(tuple(names[j] for j in combo))
        if time.time() - t0 > batas_detik:
            print(f"[riset] {P.fam}: batas waktu di k={k}")
            break
    print(f"[riset] {P.fam}: tahap 1 {len(lolos)} kombinasi, {time.time() - t0:.0f} dtk")
    hasil = [nilai(c) for c in lolos]
    # Tahap 2: perluas 40 terbaik + juara lama dengan 1 syarat tambahan
    top = sorted([h for h in hasil if h["lolos_pilih"]], key=lambda h: -(h["wr_pilih"] * 100 + h["ex_pilih"] * 5))[:40]
    basis = [h["syarat"] for h in top] + juara_lama
    for b in basis:
        for s in names:
            if s not in b:
                hasil.append(nilai(b + [s]))
    for b in juara_lama:
        nilai(b)
    print(f"[riset] {P.fam}: {len(kandidat)} kandidat dinilai, {time.time() - t0:.0f} dtk")
    return list(kandidat.values())


def pilih_lapis(P: Penguji, semua: list[dict], lama: list[dict]) -> tuple[list[dict], list[str]]:
    sah = [h for h in semua if h["lolos_pilih"] and h["lolos_baru"]]
    lama_map = {r["lapis"]: r for r in lama}
    baru, catatan, dipakai = [], [], set()
    for lapis, cak in CAKUPAN[P.fam].items():
        calon = sorted([h for h in sah if h["cakupan"] >= cak and tuple(h["syarat"]) not in dipakai],
                       key=lambda h: -h["skor"])
        inc = lama_map.get(lapis)
        inc_stat = P.stat(inc["syarat"]) if inc else None
        best = calon[0] if calon else None
        if inc_stat and (not best or best["skor"] < inc_stat["skor"] + MARGIN or
                         tuple(sorted(best["syarat"])) == tuple(sorted(inc_stat["syarat"]))):
            pilihan, status = inc_stat, "tetap"
        elif best:
            pilihan, status = best, "ganti" if inc_stat else "baru"
        else:
            continue
        dipakai.add(tuple(pilihan["syarat"]))
        baru.append({"lapis": lapis, "syarat": pilihan["syarat"], "stat": {
            k: round(v, 4) if isinstance(v, float) else v for k, v in pilihan.items()
            if k in ("n_pilih", "wr_pilih", "ex_pilih", "n_baru", "wr_baru", "ex_baru", "cakupan", "skor")}})
        catatan.append((lapis, status, pilihan, inc_stat))
    return baru, catatan


def _fmt(st):
    return (f"menang {st['wr_pilih']:.0%} · rata-rata {st['ex_pilih']:+.2f}% (periode pilih, {st['n_pilih']} trade)\n"
            f"   periode terbaru: menang {st['wr_baru']:.0%} · {st['ex_baru']:+.2f}% ({st['n_baru']} trade) · "
            f"muncul di {st["cakupan"]:.0%} hari bursa").replace(".", ",")


def laporan(hasil: dict, awal_hold: str, today: str) -> str:
    ikon = {"plus": "⭐⭐", "utama": "⭐", "cadangan": "▫️"}
    p = [f"🤖 <b>Riset otomatis mingguan</b> · {today}",
         "Data 3 tahun terbaru semua saham, bersih fee 0,4%. Dipilih di 4 periode lama, "
         f"dikonfirmasi di periode terbaru (sejak {awal_hold}) yang tidak dipakai saat memilih."]
    for fam, judul in (("BSJP", "🌙 BSJP · beli sore, jual besok pagi di open"),
                       ("BPJS", "☀️ BPJS · beli besok di open, jual besok di close")):
        p.append(f"<b>━━ {judul} ━━</b>")
        for lapis, status, st, inc in hasil[fam]:
            tanda = {"tetap": "✅ tetap", "ganti": "🔄 DIGANTI", "baru": "🆕 baru"}[status]
            baris = [f"{ikon.get(lapis, '')} <b>{lapis.upper()}</b> · {tanda}",
                     "   " + html.escape(fb.label(st["syarat"])),
                     "   " + html.escape(_fmt(st))]
            if status == "ganti" and inc:
                baris.append(f"   (sebelumnya menang {inc['wr_pilih']:.0%} / terbaru {inc['wr_baru']:.0%}, "
                             f"skor {inc['skor']:.1f} → {st['skor']:.1f})")
            p.append("\n".join(baris))
        if not hasil[fam]:
            p.append("Tidak ada aturan yang lolos; aturan lama tetap dipakai.")
    p.append("<i>Aturan diganti hanya kalau penantang jelas lebih unggul. Hasil masa lalu bukan jaminan.</i>")
    return "\n\n".join(p)


def run(kirim: bool = True, cache: dict | None = None, ihsg=None) -> dict:
    t0 = time.time()
    today = (datetime.now(timezone.utc) + timedelta(hours=7)).date().isoformat()
    if cache is None:
        cache = data.fetch_many(universe.load(), period="3y")
        ihsg = data.fetch_symbol("^JKSE", "3y")
    F = bangun_panel(cache, ihsg)
    print(f"[riset] panel {F.shape}, {time.time() - t0:.0f} dtk")
    aktif = strategi.load()
    rules = aktif.get("RULES") or {}
    hasil, ringkas, awal_hold = {}, {}, ""
    for fam in ("BSJP", "BPJS"):
        lama = rules.get(fam) or fb.AWAL[fam]
        P = Penguji(F, fam)
        awal_hold = P.awal_hold
        semua = cari(P, [r["syarat"] for r in lama] + [r["syarat"] for r in fb.AWAL[fam]])
        baru, catatan = pilih_lapis(P, semua, lama)
        if baru:
            rules[fam] = baru
        hasil[fam] = catatan
        ringkas[fam] = [(c[0], c[1]) for c in catatan]
    aktif["RULES"] = rules
    aktif["riset_terakhir"] = today
    berubah = [f"{fam} {l}" for fam, xs in ringkas.items() for l, s in xs if s != "tetap"]
    if berubah:
        aktif.setdefault("riwayat", []).append({"tanggal": today, "kategori": "RISET", "ke": berubah})
        aktif["riwayat"] = aktif["riwayat"][-30:]
    strategi.save(aktif)
    teks = laporan(hasil, awal_hold, today)
    if kirim:
        telegram_send.send(teks)
    print(f"[riset] selesai {time.time() - t0:.0f} dtk; berubah: {berubah or '-'}")
    return {"rules": rules, "teks": teks}
