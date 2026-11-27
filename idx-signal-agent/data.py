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


def fetch_symbol(sym: str, period: str = "1y") -> pd.DataFrame | None:
    """Simbol Yahoo apa adanya, mis. ^JKSE (IHSG)."""
    try:
        df = yf.download(sym, period=period, interval="1d", auto_adjust=False, progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df[["Open", "High", "Low", "Close"]].dropna()        # volume indeks bisa 0
    except Exception as e:
        print(f"[data] gagal {sym}: {e}")
        return None


def pasar_series(cache: dict, period: str = "3y") -> dict:
    """{tanggal: {"ihsg_ret1": %, "breadth": porsi saham di atas MA20}} untuk semua tanggal."""
    closes = pd.DataFrame({k: df["Close"] for k, df in cache.items()})
    breadth = (closes > closes.rolling(20, min_periods=20).mean()).sum(axis=1) / closes.notna().sum(axis=1)
    out = {str(d.date()): {"breadth": float(b), "ihsg_ret1": 0.0} for d, b in breadth.items()}
    ada = set()
    ihsg = fetch_symbol("^JKSE", period)
    if ihsg is not None:
        ic = ihsg["Close"]
        r = (ic / ic.shift(1) - 1) * 100
        up50 = ic > ic.rolling(50).mean()
        r5 = (ic / ic.shift(5) - 1) * 100
        for d, v in r.dropna().items():
            o = out.setdefault(str(d.date()), {"breadth": 0.0})
            o["ihsg_ret1"] = float(v)
            o["ihsg_up50"] = bool(up50.loc[d])
            if r5.loc[d] == r5.loc[d]:
                o["ihsg_ret5"] = float(r5.loc[d])
            ada.add(str(d.date()))
        # Hari yang belum punya IHSG: pakai status MA50 hari bursa sebelumnya
        last_up = None
        for key in sorted(out):
            if "ihsg_up50" in out[key]:
                last_up = out[key]["ihsg_up50"]
            elif last_up is not None:
                out[key]["ihsg_up50"] = last_up
    # Cadangan kalau IHSG hari itu belum ada di Yahoo: rata-rata return 50 saham terlikuid
    value = pd.DataFrame({k: df["Close"] * df["Volume"] for k, df in cache.items()})
    top = value.tail(20).mean().nlargest(50).index
    proxy = (closes[top] / closes[top].shift(1) - 1).mean(axis=1) * 100
    for d, v in proxy.dropna().items():
        key = str(d.date())
        if key not in ada and key in out:
            out[key]["ihsg_ret1"] = float(v)
    return out


def ihsg_live() -> dict:
    """IHSG saat jam bursa (data telat ±15 menit): return 1 & 5 hari."""
    ihsg = fetch_symbol("^JKSE", "1mo")
    if ihsg is None:
        return {}
    ic = ihsg["Close"].dropna()
    if len(ic) < 6:
        return {}
    return {"ihsg_ret1": float((ic.iloc[-1] / ic.iloc[-2] - 1) * 100),
            "ihsg_ret5": float((ic.iloc[-1] / ic.iloc[-6] - 1) * 100),
            "tanggal": str(ic.index[-1].date())}
