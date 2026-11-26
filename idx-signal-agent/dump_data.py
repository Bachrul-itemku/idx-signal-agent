"""Unduh OHLCV harian ±2 tahun semua saham + IHSG ke riset_data/ohlcv.csv.gz (untuk riset)."""
import os
import pandas as pd
import yfinance as yf
import data
import universe

OUT = "riset_data"
os.makedirs(OUT, exist_ok=True)

kodes = universe.load()
cache = data.fetch_many(kodes, period="3y")
rows = []
for kode, df in cache.items():
    d = df.copy()
    d["kode"] = kode
    rows.append(d.reset_index().rename(columns={"index": "Date", "Datetime": "Date"}))
panel = pd.concat(rows, ignore_index=True)
panel.columns = [str(c) for c in panel.columns]
panel.to_csv(f"{OUT}/ohlcv.csv.gz", index=False, compression="gzip", float_format="%.4f")
print("panel", panel.shape, panel["Date"].min(), panel["Date"].max())

ihsg = yf.download("^JKSE", period="3y", interval="1d", auto_adjust=False, progress=False)
if isinstance(ihsg.columns, pd.MultiIndex):
    ihsg.columns = ihsg.columns.get_level_values(0)
ihsg[["Open", "High", "Low", "Close", "Volume"]].to_csv(f"{OUT}/ihsg.csv.gz", compression="gzip")
print("ihsg", ihsg.shape)
