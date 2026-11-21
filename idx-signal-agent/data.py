"""Ambil data harian IDX dari Yahoo Finance (ticker .JK).
Data gratis ini telat ±10–15 menit saat jam bursa dan kadang bolong;
untuk produksi pertimbangkan sumber data berbayar."""
import time
import pandas as pd
import yfinance as yf
import config


def _clean(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    cols = ["Open", "High", "Low", "Close", "Volume"]
    if not set(cols) <= set(df.columns):
        return None
    df = df[cols].dropna()
    df = df[df["Volume"] > 0]
    return df if len(df) else None


def fetch(kode: str, period: str | None = None) -> pd.DataFrame | None:
    try:
        df = yf.download(f"{kode}.JK", period=period or config.HISTORY_PERIOD,
                         interval="1d", auto_adjust=False, progress=False)
    except Exception as e:
        print(f"[data] gagal {kode}: {e}")
        return None
    return _clean(df)


def fetch_many(kodes: list[str], period: str | None = None, batch: int = 100) -> dict:
    """Unduh banyak saham sekaligus per batch (jauh lebih cepat untuk ~950 saham)."""
    out = {}
    period = period or config.HISTORY_PERIOD
    for i in range(0, len(kodes), batch):
        chunk = kodes[i:i + batch]
        tickers = [f"{k}.JK" for k in chunk]
        for attempt in range(3):
            try:
                raw = yf.download(tickers, period=period, interval="1d", auto_adjust=False,
                                  group_by="ticker", threads=True, progress=False)
                break
            except Exception as e:
                print(f"[data] batch {i // batch + 1} gagal ({e}), coba lagi")
                time.sleep(5 * (attempt + 1))
        else:
            continue
        for k, t in zip(chunk, tickers):
            try:
                df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
            except KeyError:
                continue
            df = _clean(df.copy())
            if df is not None:
                out[k] = df
        time.sleep(1)                                      # jangan membanjiri Yahoo
    print(f"[data] {len(out)}/{len(kodes)} saham berhasil diunduh")
    return out
