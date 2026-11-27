"""Menerapkan aturan BSJP/BPJS dari strategi.json (hasil riset otomatis) ke data hari ini."""
import pandas as pd
import fitur_bot as fb
import signals
import strategi
from indicators import round_tick


def rules(fam: str) -> list[dict]:
    return (strategi.load().get("RULES") or {}).get(fam) or fb.AWAL[fam]


def ihsg_dengan_proxy(ihsg: pd.DataFrame | None, cache: dict) -> pd.DataFrame | None:
    """Kalau IHSG hari terakhir belum ada di Yahoo, tambahkan baris perkiraan dari
    rata-rata return 50 saham paling likuid."""
    if not cache:
        return ihsg
    hari = max(df.index[-1] for df in cache.values())
    if ihsg is not None and len(ihsg) and ihsg["Close"].dropna().index[-1] >= hari:
        return ihsg
    value = pd.DataFrame({k: (df["Close"] * df["Volume"]).tail(20) for k, df in cache.items()})
    top = value.mean().nlargest(50).index
    rets = [cache[k]["Close"].iloc[-1] / cache[k]["Close"].iloc[-2] - 1
            for k in top if cache[k].index[-1] == hari and len(cache[k]) > 1]
    if ihsg is None or not len(rets):
        return ihsg
    base = ihsg["Close"].dropna()
    c = float(base.iloc[-1]) * (1 + sum(rets) / len(rets))
    extra = pd.DataFrame({"Open": [c], "High": [c], "Low": [c], "Close": [c]}, index=[hari])
    print(f"[aturan] IHSG {hari.date()} belum ada, pakai perkiraan {sum(rets) / len(rets) * 100:+.2f}%")
    return pd.concat([base.to_frame().join(ihsg[["Open", "High", "Low"]]), extra]).sort_index()


def fitur_hari_ini(cache: dict, ihsg, tanggal: str, frac: float = 1.0) -> pd.DataFrame:
    """Baris fitur tanggal `tanggal` untuk semua saham yang bisa ditransaksikan.
    frac < 1 (jam bursa): volume & nilai hari ini diproyeksikan ke satu hari penuh."""
    rows = []
    for k, df in cache.items():
        if len(df) < 60 or str(df.index[-1].date()) != tanggal:
            continue
        try:
            rows.append(fb.per_saham(df, k).iloc[[-1]])
        except Exception as e:
            print(f"[aturan] {k} dilewati: {e}")
    if not rows:
        return pd.DataFrame()
    F = pd.concat(rows, ignore_index=True)
    if frac < 1:
        F["volr"] = F["volr"] / frac
        F["val"] = F["val"] / frac
    F = fb.lengkapi(F, ihsg_dengan_proxy(ihsg, cache))
    return F[fb.bisa_ditransaksikan(F)].reset_index(drop=True)


def _info(r) -> dict:
    return {"kode": r.kode, "tanggal": str(pd.Timestamp(r.Date).date()), "close": float(r.c),
            "chg_pct": round(float(r.ret1), 2), "vol_ratio": round(float(r.volr), 2),
            "value_miliar": round(float(r.val), 2), "rsi": round(float(r.rsi14), 1),
            "ret5": round(float(r.ret5), 2)}


def sinyal(F: pd.DataFrame, fam: str) -> tuple[list[dict], dict]:
    """Return (sinyal, syarat_gagal). Tiap saham masuk lapis tertinggi yang ia penuhi."""
    out, sudah = [], set()
    aturan = rules(fam)
    for urut, r in enumerate(aturan):
        if F.empty:
            break
        m = fb.mask(F, r["syarat"])
        for _, row in F[m].iterrows():
            if row.kode in sudah:
                continue
            sudah.add(row.kode)
            c = float(row.c)
            if fam == "BSJP":
                plan, mode = signals.plan_bsjp(c, float(row.l)), "bsjp"
            else:
                plan, mode = {**signals.plan_bpjs(c), "sl": None, "tp1": None}, "next_day"
            out.append({**_info(row), "signal": {
                "tipe": fam, "mode": mode, "lapis": r["lapis"], "resep": f"AUTO_{fam}_{r['lapis']}",
                "skor": 100 - 15 * urut, "alasan": fb.label(r["syarat"]), "stat": r.get("stat", {}), **plan}})
    # Syarat lapis utama (atau pertama) yang paling sering tidak terpenuhi
    gagal = {}
    if not F.empty and aturan:
        acuan = next((r for r in aturan if r["lapis"] == "utama"), aturan[0])
        for s in acuan["syarat"]:
            n = int((~fb._b(fb.S[s][0](F))).sum())
            if n:
                gagal[f"tidak {fb.S[s][1]}"] = n
    return out, gagal


def teks_stat(st: dict) -> str:
    if not st:
        return ""
    return (f"📊 Riset: menang {st.get('wr_pilih', 0):.0%}, rata-rata {st.get('ex_pilih', 0):+.2f}% bersih; "
            f"periode terbaru menang {st.get('wr_baru', 0):.0%}").replace(".", ",")
