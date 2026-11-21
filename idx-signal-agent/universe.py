"""Daftar semua kode saham IDX.
1. Coba ambil daftar terbaru dari situs BEI (kadang diblokir, tidak apa-apa).
2. Kalau gagal, pakai tickers.txt (disimpan di repo).
3. Kode di WATCHLIST selalu ikut (untuk saham IPO baru yang belum ada di daftar)."""
import os
import requests
import config

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tickers.txt")
IDX_URL = ("https://www.idx.co.id/primary/StockData/GetSecuritiesStock"
           "?start=0&length=9999&code=&sector=&board=&language=id-id")


def _from_idx() -> set[str]:
    try:
        r = requests.get(IDX_URL, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
            "Accept": "application/json", "Referer": "https://www.idx.co.id/",
        })
        rows = r.json().get("data", [])
        codes = {row["Code"].strip().upper() for row in rows if row.get("Code")}
        return codes if len(codes) > 500 else set()
    except Exception as e:
        print(f"[universe] daftar BEI tidak bisa diambil ({type(e).__name__}), pakai tickers.txt")
        return set()


def load() -> list[str]:
    codes = _from_idx()
    if codes:
        with open(FILE, "w") as f:                       # perbarui file untuk run berikutnya
            f.write("\n".join(sorted(codes)) + "\n")
    else:
        with open(FILE) as f:
            codes = {line.strip().upper() for line in f if line.strip()}
    codes |= set(config.WATCHLIST)
    return sorted(codes)


def scan_list() -> list[str]:
    return load() if config.UNIVERSE == "ALL" else list(config.WATCHLIST)
