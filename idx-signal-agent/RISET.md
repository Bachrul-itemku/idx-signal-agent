# Riset strategi (26 Nov 2026)

Data: harian Yahoo, 891 saham IDX, Nov 2023 – Nov 2026. Hanya saham dengan rata-rata nilai transaksi
20 hari ≥ 1 M. Semua hasil sudah dipotong fee 0,4% per trade (beli + jual).

Metode: ±46 ribu kombinasi 1–3 syarat (termasuk analisa di luar skill: RSI2, IBS, Bollinger, gap,
kondisi IHSG, breadth pasar, 52 minggu, NR7, dll.) × 13–18 aturan keluar. Periode dibagi berurutan:
**cari** (Okt 2024 – Jan 2026) → **saring** (Jan – Jul 2026) → **uji** (Jul – Nov 2026). Periode uji
tidak pernah dipakai untuk memilih.

## Temuan penting
1. **Jebakan 85% menang palsu**: saham terkunci di ARA 10% (FCA, open = high = low = close) membuat
   backtest tampak menang 85–89%. Saham seperti itu tidak bisa dibeli (antre). Sekarang dibuang
   (`signals.terkunci`).
2. **Tidak ada strategi yang jujur mendekati 100% menang.** Yang bertahan di periode uji: 55–70%.
3. Resep BPJS momentum lama (SKOR8, KOKO, HC2D, GREEN_HAMMER) konsisten **rugi** (menang 26–33%).

## Yang dipakai bot
| Resep | Syarat | Masuk / keluar | Menang (cari / saring / uji) | Rata-rata bersih / trade |
|---|---|---|---|---|
| `BSJP_MOMBB` | close > upper BB, naik > 4%, rata nilai 20 hr ≥ 50 M, harga 200–1.000 | beli close (post-trading), jual open besok | 68% / 67% / 72% | +0,6% / +0,6% / +0,8% |
| `BPJS_DIP` | turun > 4%, close < lower BB, IHSG turun > 1%, rata nilai ≥ 10 M | beli open besok, jual close besok | 57% / 57% / 59% | +0,6% / +2,1% / +2,1% |

Keduanya bertransaksi di harga lelang (pembukaan/penutupan), jadi tidak kena selisih bid-offer.

## Dicoba tapi tidak dipakai
- `BASE_RECOVERY` (di atas MA20, ≤ 10% dari low 52 minggu, harga < 200): menang 85% di 2026, tetapi
  mayoritas saham dekat gocap; setelah biaya 1 tick negatif di 2024–25. Rapuh, tidak aktif.
- Target kecil + cut lebar (mis. TP 1% / SL 5%) menaikkan winrate tapi rata-rata hasil turun.

## Batasan
Data harian (urutan intraday tidak diketahui; kalau TP & SL tersentuh di hari yang sama dianggap SL),
daftar saham hanya yang masih tercatat sekarang (survivorship bias), dan 2026 sebagian besar pasar naik.
Ulang riset: workflow "Riset - ambil data" → branch `data-riset`.
