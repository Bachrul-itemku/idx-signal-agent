"""Fitur & pustaka syarat yang SAMA untuk riset otomatis dan sinyal live.
Fitur hanya memakai info yang tersedia saat keputusan (close hari itu untuk BSJP/BPJS malam)."""
import numpy as np
import pandas as pd

FEE = 0.4   # % beli + jual


def _rsi(s, n):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))


def _ara(p):
    return np.where(p < 200, 0.35, np.where(p < 5000, 0.25, 0.20))


def per_saham(df: pd.DataFrame, kode: str, hasil: bool = False) -> pd.DataFrame:
    """df = OHLCV harian (index tanggal). hasil=True menambah kolom hasil trade (untuk riset)."""
    c, o, h, l, v = df["Close"], df["Open"], df["High"], df["Low"], df["Volume"]
    p1 = c.shift(1)
    rng = (h - l).replace(0, np.nan)
    ma5, ma20, ma50, ma200 = (c.rolling(n).mean() for n in (5, 20, 50, 200))
    sd = c.rolling(20).std(ddof=0)
    bw = 4 * sd / ma20
    vavg = v.shift(1).rolling(20).mean()
    tr = pd.concat([h - l, (h - p1).abs(), (l - p1).abs()], axis=1).max(axis=1)
    ret1 = (c / p1 - 1) * 100
    down, up = (c < p1).astype(int), (c > p1).astype(int)
    hi20r, lo20r = h.rolling(20).max(), l.rolling(20).min()
    hi20 = c > h.shift(1).rolling(20).max()
    volr = v / vavg
    F = pd.DataFrame({
        "Date": df.index, "kode": kode, "c": c.values, "o": o.values, "h": h.values, "l": l.values,
        "ret1": ret1.values, "ret5": ((c / c.shift(5) - 1) * 100).values,
        "ret20": ((c / c.shift(20) - 1) * 100).values, "gap": ((o / p1 - 1) * 100).values,
        "ibs": ((c - l) / rng).fillna(0.5).values, "body": ((c - o) / o * 100).values,
        "uwick": ((h - np.maximum(c, o)) / rng).fillna(0).values,
        "lwick": ((np.minimum(c, o) - l) / rng).fillna(0).values,
        "d_ma5": ((c / ma5 - 1) * 100).values, "d_ma10": ((c / c.rolling(10).mean() - 1) * 100).values,
        "d_ma20": ((c / ma20 - 1) * 100).values, "d_ma50": ((c / ma50 - 1) * 100).values,
        "d_ma200": ((c / ma200 - 1) * 100).values,
        "ma20_up": (ma20.diff(5) > 0).values, "ma50_up": (ma50.diff(10) > 0).values,
        "ma_susun": ((c > ma5) & (ma5 > ma20) & (ma20 > ma50)).values,
        "rsi2": _rsi(c, 2).values, "rsi14": _rsi(c, 14).values,
        "volr": volr.values, "volr5": volr.shift(1).rolling(5).mean().values,
        "val": (c * v / 1e9).values, "valavg": ((c * v).shift(1).rolling(20).mean() / 1e9).values,
        "atrp": (tr.rolling(14).mean() / c * 100).values,
        "hi20": hi20.values, "hi20_baru": (hi20 & ~hi20.shift(1, fill_value=False)).values,
        "hi52": (c > h.shift(1).rolling(250).max()).values,
        "d_hi52": ((c / h.rolling(250).max() - 1) * 100).values,
        "d_lo52": ((c / l.rolling(250).min() - 1) * 100).values,
        "pos20": ((c - lo20r) / (hi20r - lo20r).replace(0, np.nan)).values,
        "streak_dn": down.groupby((down == 0).cumsum()).cumsum().values,
        "streak_up": up.groupby((up == 0).cumsum()).cumsum().values,
        "ret1_kmrn": ret1.shift(1).values,
        "bbpos": ((c - (ma20 - 2 * sd)) / (4 * sd)).values,
        "bb_sq": (bw <= bw.rolling(120).quantile(0.15)).values,
        "nr7": ((h - l) <= (h - l).rolling(7).min()).values,
        "inside": ((h <= h.shift(1)) & (l >= l.shift(1))).values,
        "ara": (ret1 >= _ara(p1.fillna(c)) * 100 - 0.5).values,
        "terkunci": ((h == l) | ((c >= h) & (ret1 >= 9.4))).values,
        "flat20": (h == l).astype(float).rolling(20).mean().values,
    })
    F["dow"] = pd.to_datetime(F["Date"]).dt.dayofweek
    if hasil:
        o1, c1 = o.shift(-1), c.shift(-1)
        F["n_gap"] = ((o1 / c - 1) * 100).values
        F["bsjp_open"] = ((o1 / c - 1) * 100 - FEE).values        # beli close, jual open besok
        F["bpjs_close"] = ((c1 / o1 - 1) * 100 - FEE).values      # beli open besok, jual close besok
        bad = ((c1 / c - 1).abs() > 0.40).values
        F.loc[bad, ["bsjp_open", "bpjs_close"]] = np.nan
    return F


def pasar(ihsg: pd.DataFrame | None) -> pd.DataFrame:
    """Fitur IHSG per tanggal."""
    if ihsg is None or ihsg.empty:
        return pd.DataFrame(columns=["Date"])
    ic = ihsg["Close"].dropna()
    return pd.DataFrame({
        "Date": ic.index, "ihsg_ret1": ((ic / ic.shift(1) - 1) * 100).values,
        "ihsg_ret5": ((ic / ic.shift(5) - 1) * 100).values, "ihsg_ret20": ((ic / ic.shift(20) - 1) * 100).values,
        "ihsg_up20": (ic > ic.rolling(20).mean()).values, "ihsg_up50": (ic > ic.rolling(50).mean()).values,
        "ihsg_rsi2": _rsi(ic, 2).values,
    })


def lengkapi(F: pd.DataFrame, ihsg: pd.DataFrame | None) -> pd.DataFrame:
    """Tambah fitur pasar, breadth, dan ranking lintas saham per tanggal."""
    P = pasar(ihsg)
    F = F.merge(P, on="Date", how="left") if len(P) else F.assign(ihsg_ret1=np.nan)
    F["breadth"] = F.groupby("Date")["d_ma20"].transform(lambda s: (s > 0).mean())
    F["rel_ihsg20"] = F["ret20"] - F.get("ihsg_ret20", np.nan)
    lik = (F["valavg"] >= 1) & (F["c"] > 50)
    for col, nama in (("ret20", "rk_ret20"), ("ret5", "rk_ret5"), ("ret1", "rk_ret1"), ("val", "rk_val")):
        F[nama] = np.nan
        F.loc[lik, nama] = F[lik].groupby("Date")[col].rank(pct=True)
    return F


def bisa_ditransaksikan(F: pd.DataFrame) -> pd.Series:
    return (F["valavg"] >= 1) & (F["c"] > 50) & ~F["ara"].astype(bool) & ~F["terkunci"].astype(bool) \
        & (F["flat20"] < 0.1) & F["d_ma200"].notna()


# ---------- Pustaka syarat: nama → (fungsi atas DataFrame fitur, label untuk manusia) ----------
def _b(x):
    return x.fillna(False).astype(bool) if hasattr(x, "fillna") else x


S = {
    "ma20+": (lambda F: F.d_ma20 > 0, "di atas MA20"),
    "ma50+": (lambda F: F.d_ma50 > 0, "di atas MA50"),
    "ma200+": (lambda F: F.d_ma200 > 0, "di atas MA200"),
    "ma20naik": (lambda F: _b(F.ma20_up), "MA20 menanjak"),
    "ma50naik": (lambda F: _b(F.ma50_up), "MA50 menanjak"),
    "ma_susun": (lambda F: _b(F.ma_susun), "harga > MA5 > MA20 > MA50"),
    "ma5-": (lambda F: F.d_ma5 < 0, "di bawah MA5"),
    "jauh_ma20>10": (lambda F: F.d_ma20 > 10, "> 10% di atas MA20"),
    "dekat_ma20": (lambda F: F.d_ma20.abs() < 3, "dekat MA20 (±3%)"),
    "naik>2": (lambda F: F.ret1 > 2, "naik > 2%"),
    "naik>4": (lambda F: F.ret1 > 4, "naik > 4%"),
    "naik>6": (lambda F: F.ret1 > 6, "naik > 6%"),
    "naik<10": (lambda F: F.ret1 < 10, "naik < 10% (bukan pucuk)"),
    "naik2-8": (lambda F: F.ret1.between(2, 8), "naik 2–8%"),
    "turun>2": (lambda F: F.ret1 < -2, "turun > 2%"),
    "turun>4": (lambda F: F.ret1 < -4, "turun > 4%"),
    "turun>6": (lambda F: F.ret1 < -6, "turun > 6%"),
    "r5>5": (lambda F: F.ret5 > 5, "naik > 5% dalam 5 hari"),
    "r5<-5": (lambda F: F.ret5 < -5, "turun > 5% dalam 5 hari"),
    "r5<-10": (lambda F: F.ret5 < -10, "turun > 10% dalam 5 hari"),
    "r20>10": (lambda F: F.ret20 > 10, "naik > 10% dalam 20 hari"),
    "r20<-10": (lambda F: F.ret20 < -10, "turun > 10% dalam 20 hari"),
    "rsi2<5": (lambda F: F.rsi2 < 5, "RSI2 < 5"),
    "rsi2<10": (lambda F: F.rsi2 < 10, "RSI2 < 10"),
    "rsi2>90": (lambda F: F.rsi2 > 90, "RSI2 > 90"),
    "rsi14<30": (lambda F: F.rsi14 < 30, "RSI14 < 30"),
    "rsi14>70": (lambda F: F.rsi14 > 70, "RSI14 > 70"),
    "rsi14<75": (lambda F: F.rsi14 < 75, "RSI14 < 75"),
    "ibs<0.2": (lambda F: F.ibs < 0.2, "close dekat low hari itu"),
    "ibs>0.8": (lambda F: F.ibs > 0.8, "close dekat high hari itu"),
    "ibs>0.95": (lambda F: F.ibs > 0.95, "close hampir = high"),
    "bb>1": (lambda F: F.bbpos > 1, "tembus upper Bollinger"),
    "bb<0": (lambda F: F.bbpos < 0, "di bawah lower Bollinger"),
    "uwick<0.1": (lambda F: F.uwick < 0.1, "tanpa ekor atas"),
    "hammer": (lambda F: F.lwick > 0.5, "ekor bawah panjang"),
    "body>3": (lambda F: F.body > 3, "badan candle hijau > 3%"),
    "up3": (lambda F: F.streak_up >= 3, "naik 3 hari beruntun"),
    "dn3": (lambda F: F.streak_dn >= 3, "turun 3 hari beruntun"),
    "vol>1.5": (lambda F: F.volr > 1.5, "volume > 1,5x rata-rata"),
    "vol>2": (lambda F: F.volr > 2, "volume > 2x rata-rata"),
    "vol>3": (lambda F: F.volr > 3, "volume > 3x rata-rata"),
    "vol<1.5": (lambda F: F.volr < 1.5, "volume < 1,5x rata-rata"),
    "vol_kering": (lambda F: F.volr5 < 0.8, "volume 5 hari sebelumnya sepi"),
    "nilai>5M": (lambda F: F.val > 5, "nilai transaksi > 5 M"),
    "nilai>20M": (lambda F: F.val > 20, "nilai transaksi > 20 M"),
    "rata>=10M": (lambda F: F.valavg >= 10, "rata nilai 20 hari ≥ 10 M"),
    "rata>=20M": (lambda F: F.valavg >= 20, "rata nilai 20 hari ≥ 20 M"),
    "rata>=50M": (lambda F: F.valavg >= 50, "rata nilai 20 hari ≥ 50 M"),
    "rata>=100M": (lambda F: F.valavg >= 100, "rata nilai 20 hari ≥ 100 M"),
    "hi20": (lambda F: _b(F.hi20), "tembus high 20 hari"),
    "hi20_baru": (lambda F: _b(F.hi20_baru), "hari pertama tembus high 20 hari"),
    "hi52": (lambda F: _b(F.hi52), "tembus high 52 minggu"),
    "dekat_hi52": (lambda F: F.d_hi52 > -5, "≤ 5% dari high 52 minggu"),
    "dekat_lo52": (lambda F: F.d_lo52 < 10, "≤ 10% dari low 52 minggu"),
    "pos20>0.9": (lambda F: F.pos20 > 0.9, "di puncak rentang 20 hari"),
    "pos20<0.1": (lambda F: F.pos20 < 0.1, "di dasar rentang 20 hari"),
    "atr<3": (lambda F: F.atrp < 3, "volatilitas rendah (ATR < 3%)"),
    "atr<5": (lambda F: F.atrp < 5, "ATR < 5%"),
    "atr>5": (lambda F: F.atrp > 5, "volatilitas tinggi (ATR > 5%)"),
    "bb_squeeze": (lambda F: _b(F.bb_sq), "Bollinger menyempit"),
    "nr7": (lambda F: _b(F.nr7), "rentang tersempit 7 hari"),
    "inside": (lambda F: _b(F.inside), "inside bar"),
    "kmrn_naik": (lambda F: F.ret1_kmrn > 0, "kemarin naik"),
    "kmrn_turun": (lambda F: F.ret1_kmrn < 0, "kemarin turun"),
    "gap_up>1": (lambda F: F.gap > 1, "hari ini buka gap up > 1%"),
    "gap_down": (lambda F: F.gap < 0, "hari ini buka gap down"),
    "harga100-2000": (lambda F: F.c.between(100, 2000), "harga 100–2.000"),
    "harga200-1000": (lambda F: F.c.between(200, 1000), "harga 200–1.000"),
    "harga<500": (lambda F: F.c < 500, "harga < 500"),
    "harga>500": (lambda F: F.c > 500, "harga > 500"),
    "bukan_jumat": (lambda F: F.dow != 4, "bukan hari Jumat"),
    "rs20_top20%": (lambda F: F.rk_ret20 > 0.8, "20% terkuat (20 hari)"),
    "rs5_top10%": (lambda F: F.rk_ret5 > 0.9, "10% terkuat (5 hari)"),
    "rs5_bawah10%": (lambda F: F.rk_ret5 < 0.1, "10% terlemah (5 hari)"),
    "nilai_top10%": (lambda F: F.rk_val > 0.9, "10% nilai transaksi terbesar hari itu"),
    "kuat_vs_ihsg": (lambda F: F.rel_ihsg20 > 0, "lebih kuat dari IHSG (20 hari)"),
    "lemah_vs_ihsg": (lambda F: F.rel_ihsg20 < 0, "lebih lemah dari IHSG (20 hari)"),
    "ihsg>ma20": (lambda F: _b(F.ihsg_up20 == True), "IHSG di atas MA20"),
    "ihsg>ma50": (lambda F: _b(F.ihsg_up50 == True), "IHSG di atas MA50"),
    "ihsg_naik": (lambda F: F.ihsg_ret1 > 0, "IHSG naik hari ini"),
    "ihsg_turun>1": (lambda F: F.ihsg_ret1 < -1, "IHSG turun > 1% hari ini"),
    "ihsg_turun>2": (lambda F: F.ihsg_ret1 < -2, "IHSG turun > 2% hari ini"),
    "ihsg_r5>0": (lambda F: F.ihsg_ret5 > 0, "IHSG naik dalam 5 hari"),
    "ihsg_r5<-3": (lambda F: F.ihsg_ret5 < -3, "IHSG turun > 3% dalam 5 hari"),
    "ihsg_r20<-5": (lambda F: F.ihsg_ret20 < -5, "IHSG turun > 5% dalam 20 hari"),
    "ihsg_rsi2<10": (lambda F: F.ihsg_rsi2 < 10, "IHSG jenuh jual (RSI2 < 10)"),
    "breadth>50": (lambda F: F.breadth > 0.5, "> 50% saham di atas MA20"),
    "breadth<30": (lambda F: F.breadth < 0.3, "< 30% saham di atas MA20"),
}


def mask(F: pd.DataFrame, syarat: list[str]) -> pd.Series:
    m = pd.Series(True, index=F.index)
    for s in syarat:
        m &= _b(S[s][0](F))
    return m


def label(syarat: list[str]) -> str:
    return ", ".join(S[s][1] for s in syarat if s in S)


# ---------- Aturan awal (hasil riset ronde 1–2, dipakai sampai riset otomatis menemukan yang lebih baik)
AWAL = {
    "BSJP": [
        {"lapis": "plus", "syarat": ["bb>1", "naik>4", "naik<10", "rata>=50M", "harga200-1000", "ihsg_r5>0"]},
        {"lapis": "utama", "syarat": ["bb>1", "naik>4", "rata>=50M", "harga200-1000"]},
        {"lapis": "cadangan", "syarat": ["bb>1", "naik>4", "naik<10", "rata>=20M", "harga100-2000", "ihsg_r5>0"]},
    ],
    "BPJS": [
        {"lapis": "plus", "syarat": ["turun>4", "bb<0", "ihsg_turun>2", "rata>=10M", "ibs<0.2"]},
        {"lapis": "utama", "syarat": ["turun>4", "bb<0", "ihsg_turun>1", "rata>=10M", "ibs<0.2"]},
    ],
}
