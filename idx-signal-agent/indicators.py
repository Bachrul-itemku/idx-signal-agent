"""Indikator teknikal, Volume Profile, fractal, divergence, Fibonacci.
Semua deterministik (tanpa AI) dan hanya butuh data OHLCV harian."""
import numpy as np
import pandas as pd


def tick_size(price: float) -> int:
    """Fraksi harga BEI."""
    if price < 200:
        return 1
    if price < 500:
        return 2
    if price < 2000:
        return 5
    if price < 5000:
        return 10
    return 25


def round_tick(price: float, mode: str = "down") -> float:
    t = tick_size(price)
    f = np.floor if mode == "down" else np.ceil
    return float(f(price / t) * t)


def volume_profile(df: pd.DataFrame, bins: int = 40, value_area: float = 0.70) -> dict:
    """POC / VAH / VAL dari N candle terakhir.
    Volume tiap candle dibagi rata ke rentang low–high-nya."""
    lo, hi = df["Low"].min(), df["High"].max()
    edges = np.linspace(lo, hi, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2
    hist = np.zeros(bins)
    for l, h, v in zip(df["Low"], df["High"], df["Volume"]):
        mask = (centers >= l) & (centers <= h)
        n = mask.sum()
        if n == 0:
            hist[np.argmin(np.abs(centers - (l + h) / 2))] += v
        else:
            hist[mask] += v / n

    poc_i = int(hist.argmax())
    total, acc = hist.sum(), hist[poc_i]
    lo_i = hi_i = poc_i
    while acc < value_area * total:
        up = hist[hi_i + 1] if hi_i + 1 < bins else -1
        dn = hist[lo_i - 1] if lo_i - 1 >= 0 else -1
        if up >= dn:
            hi_i += 1
            acc += up
        else:
            lo_i -= 1
            acc += dn

    return {"poc": float(centers[poc_i]), "vah": float(edges[hi_i + 1]), "val": float(edges[lo_i])}


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    d = close.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def fractals(df: pd.DataFrame, n: int = 2):
    """Fractal Bill Williams 5 candle (seperti chart /C KODE F5).
    Merah (atas) = puncak lokal/resisten, hijau (bawah) = lembah lokal/support.
    Hanya fractal yang sudah terkonfirmasi (punya n candle di kanannya)."""
    h, l = df["High"].to_numpy(), df["Low"].to_numpy()
    red = pd.Series(np.nan, index=df.index)
    green = pd.Series(np.nan, index=df.index)
    for i in range(n, len(df) - n):
        left_h, right_h = h[i - n:i], h[i + 1:i + n + 1]
        if h[i] > left_h.max() and h[i] >= right_h.max():
            red.iloc[i] = h[i]
        left_l, right_l = l[i - n:i], l[i + 1:i + n + 1]
        if l[i] < left_l.min() and l[i] <= right_l.min():
            green.iloc[i] = l[i]
    return red, green


def bullish_divergence(close: pd.Series, rsi_s: pd.Series, lookback: int = 40, recent: int = 10) -> bool:
    """Harga membuat low setara/lebih rendah, RSI membuat low lebih tinggi.
    (Pendekatan dari RSI Composite I59 metode FCAAK, memakai RSI14 biasa.)"""
    c, r = close.iloc[-lookback:], rsi_s.iloc[-lookback:]
    if c.isna().any() or r.isna().any():
        return False
    i_recent = c.iloc[-recent:].idxmin()
    i_prior = c.iloc[:-recent].idxmin()
    return bool(c[i_recent] <= c[i_prior] * 1.01 and r[i_recent] > r[i_prior] + 3 and r[i_prior] < 40)


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["Close"]
    df["MA20"] = c.rolling(20).mean()
    df["MA50"] = c.rolling(50).mean()
    df["RSI"] = rsi(c)
    df["VolMA20"] = df["Volume"].rolling(20).mean()
    df["Value"] = c * df["Volume"]
    df["ValueMA20"] = df["Value"].rolling(20).mean()
    sd = c.rolling(20).std(ddof=0)
    df["BB_mid"], df["BB_up"], df["BB_low"] = df["MA20"], df["MA20"] + 2 * sd, df["MA20"] - 2 * sd
    df["BB_width"] = (df["BB_up"] - df["BB_low"]) / df["BB_mid"]
    return df
