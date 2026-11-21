"""Ambil data harian IDX dari Yahoo Finance (ticker .JK).
Data gratis ini kadang telat/bolong; untuk produksi pertimbangkan sumber data berbayar."""
import pandas as pd
import yfinance as yf
import config


def fetch(kode: str) -> pd.DataFrame | None:
    try:
        df = yf.download(f"{kode}.JK", period=config.HISTORY_PERIOD,
                         interval="1d", auto_adjust=False, progress=False)
    except Exception as e:
        print(f"[data] gagal {kode}: {e}")
        return None
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    return df[df["Volume"] > 0]
