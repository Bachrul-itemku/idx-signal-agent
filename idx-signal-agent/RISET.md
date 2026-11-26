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

## Swing
- Pencarian kombinasi baru (dengan biaya 1 tick): kandidat terbaik `ma200+ & dekat_lo52` menang 95% di
  periode uji, tetapi hanya 18 saham (didominasi MPMX & saham gocap); tanpa saham < 100 periode cari rugi.
  Tidak dipakai. `BASE_RECOVERY` sama: rapuh, tidak aktif.
- IHSG turun ±35% (8.647 → 5.643, Des 2025 – Jun 2026); hampir semua swing rugi di periode itu.
- 10 tipe swing bot diuji 2 tahun (fee + 1 tick). Dengan filter **IHSG > MA50**:

| Tipe | Menang cari / uji | Rata-rata cari / uji |
|---|---|---|
| MA_GC | 45% / 52% | +3,2% / +3,3% |
| GZ_FIBO | 50% / 62% | +3,2% / +4,4% |
| FR4_BREAKOUT | 45% / 53% | +2,9% / +1,9% |
| HBO_VOL | 49% / 50% | +6,9% / +1,6% |

  VP_VAL_BOUNCE, FR2_PULLBACK, BB_BOUNCE, STATS_REV, FCAAK rugi di semua periode → tidak aktif.
- Aturan bot: swing hanya dikirim saat IHSG > MA50 (`signals.analyze`).
- Target kecil + cut lebar (mis. TP 1% / SL 5%) menaikkan winrate tapi rata-rata hasil turun.

## Batasan
Data harian (urutan intraday tidak diketahui; kalau TP & SL tersentuh di hari yang sama dianggap SL),
daftar saham hanya yang masih tercatat sekarang (survivorship bias), dan 2026 sebagian besar pasar naik.
Ulang riset: workflow "Riset - ambil data" → branch `data-riset`.
