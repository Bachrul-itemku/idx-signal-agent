# Agent Sinyal Saham IDX → Telegram

## Ringkas
- **Memindai semua saham IDX** (±950 kode di `tickers.txt`, otomatis diperbarui dari situs BEI kalau bisa diakses). Saham gocap dan saham yang nilai transaksinya < 1 miliar dilewati.
- **09.00–11.00 WIB, tiap ±10 menit: BPJS live.** Syarat: open = low, harga di atas open & MA20, naik 1–5%, volume ≥1,5x normal (disesuaikan jam). Kandidat baru langsung dikirim dengan harga masuk, target +2,5%/+4%, dan cut di bawah open.
- **15.00–15.50 WIB, tiap ±10 menit: BSJP live.** Syarat: hijau, di atas MA20, naik 2–15%, volume di atas normal, nilai transaksi besar. Dikirim dengan harga masuk (s.d. 15.49), target besok pagi +2%/+3%, dan cut.
- Saham yang sudah dikirim tidak dikirim ulang di hari yang sama. Kalau tidak ada yang baru, bot diam.
- **18.47 WIB**: daftar **BPJS besok** (jadi ⭐ prioritas di BPJS live pagi) + sinyal swing + peringatan exit untuk saham di `WATCHLIST`.
- **Sabtu 07.13 WIB: evaluasi mingguan semua strategi** (`python main.py mingguan`), prinsipnya sama: pakai cara dengan winrate tertinggi yang rata-ratanya tetap untung.
  - **BSJP & BPJS (riset otomatis).** Unduh data 3 tahun terbaru, uji ±110 ribu kombinasi syarat (`fitur_bot.py`), pilih di 4 periode lama dan konfirmasi di periode terbaru, pakai penyusutan statistik untuk sampel kecil. Aturan per lapis (plus/utama/cadangan) disimpan di `strategi.json` dan langsung dipakai bot; juara lama hanya diganti kalau penantang unggul jelas. Laporan dikirim ke Telegram.
  - **Swing.** Backtest ±2 tahun semua tipe swing dengan jarak target bawaan/1R/1,5R/2R; dipilih maks. 6 tipe dengan winrate tertinggi yang rata-ratanya untung (`strategi.json`: `SWING`, `SWING_TP`).
- Rapor winrate kapan saja: Run workflow dengan perintah `stats`.
- `UNIVERSE=WATCHLIST` (variabel GitHub) kalau mau kembali hanya memindai watchlist.

Memindai watchlist tiap sore, menghitung Volume Profile (POC/VAH/VAL), lalu mengirim sinyal ke Telegram.
AI (Claude) hanya meninjau dan memberi komentar. Angka entry/SL/TP selalu dihitung kode.

## Alur
1. `data.py` mengambil data harian 2 tahun dari Yahoo Finance (`BBCA.JK`, dst).
2. `signals.py` menghitung sinyal dengan kaidah skill saham-idx-hqbot:

| Sinyal | Syarat inti | SL / Target |
|---|---|---|
| VAL Bounce | Sentuh VAL, ditolak, tidak dekat POC | 2 fraksi di bawah VAL / POC |
| VAH Breakout | Close tembus VAH, volume ≥1,5x MA20 | 2 fraksi di bawah VAH / 2R |
| FR4 Breakout | Tembus fractal merah + VSPIKE1/KOKO | Di bawah fractal hijau / 2R |
| FR2 Pullback | Koreksi ≤4% di atas fractal hijau baru, di atas MA50 | Di bawah fractal hijau / fractal merah terdekat |
| FCAAK | Bullish divergence RSI + ≥3 dari 4 pilar (squeeze BB, divergence, spike volume, area bottom Fibo/lower BB) | Di bawah low 20 hari / mid BB atau upper BB |
| Golden Cross | MA20 memotong MA50 ≤3 hari terakhir, nilai ≥1M | Di bawah low 10 hari / 2R |
| Stats Rev | Memantul 3–15% dari low 52 minggu, candle hijau | Di bawah low 52 minggu / 2R |
| BPJS | ≥6 dari 8 filter: IJO, KOKO, PASMA20, HC2D, TVAL3, PCH 2–8%, VSPIKE1, HHHL | Rencana pagi: cut di bawah low 15 menit, TP +2,5% |
| Peringatan exit | FR5 (jebol fractal hijau) atau close jebol VAL | Untuk yang sedang pegang |

   Semua sinyal beli wajib RR ≥1,5 dan nilai transaksi rata-rata ≥1 miliar. Skor = 50 + bonus filter pendukung.
   Lot dihitung seperti `/MM`: risiko `RISK_PCT`% dari `MODAL_RP`.
3. **Yang tidak bisa dihitung** (butuh data bot): broker (NBS1, AC3D), asing (NF3D), frekuensi (I106/MFQ), bid-offer (BPR/BOR).
   Spike frekuensi FCAAK didekati dengan spike volume, dan RSI Composite didekati dengan RSI14.
   Karena itu setiap sinyal disertai perintah verifikasi untuk @HQSahamIDX_bot, misalnya `/C KODE P1,O5,I59,I106` atau `/PNBSRATIO KODE 5 10`.
4. `agent.py` mengirim kandidat ke Claude, yang sudah dibekali kaidah HQSaham (jangan entri di POC, breakout wajib volume, fractal itu terlambat, dll.). Claude memilih maksimal 10 sinyal dan memberi komentar.
5. `telegram_send.py` mengirim pesan dalam tiga bagian: Sinyal swing, Watchlist BPJS besok, dan Peringatan exit.

## Setup
```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="123:ABC..."   # dari @BotFather
export TELEGRAM_CHAT_ID="123456789"      # ID chat/grup/channel tujuan
export ANTHROPIC_API_KEY="sk-ant-..."    # opsional; tanpa ini sinyal dikirim mentah
export WATCHLIST="BBCA,TLKM,ASII,ADRO"   # opsional
python main.py
```
Cara dapat chat ID: kirim pesan ke bot kamu, lalu buka
`https://api.telegram.org/bot<TOKEN>/getUpdates` dan lihat `chat.id`.
Untuk channel, jadikan bot sebagai admin; chat ID-nya diawali `-100`.

## Jurnal & winrate (`journal.py`, file `signals.db`)
Setiap kandidat sinyal disimpan ke SQLite, termasuk yang dibuang AI, supaya kelihatan apakah filter AI benar-benar membantu.
Tiap kali scan harian jalan, sinyal yang masih OPEN dievaluasi:
- **WIN**: high menyentuh TP1. **LOSS**: low menyentuh SL. Kalau keduanya tersentuh di hari yang sama, dihitung LOSS (konservatif).
- **EXPIRED**: 20 hari bursa tanpa kena keduanya, dinilai di harga close.
- **VAL Breakdown**: BENAR kalau close 5 hari kemudian lebih rendah.

`python main.py stats` mengirim rapor ke Telegram: winrate, rata-rata untung/rugi, dan expectancy per jenis sinyal, ditambah perbandingan "Dipilih AI" vs "Dibuang AI".
Asumsi: entry di close hari sinyal, belum termasuk fee (~0,15–0,25%) dan slippage. Butuh puluhan sinyal sebelum angkanya berarti.

Buka datanya langsung: `sqlite3 signals.db "select * from signals"`, atau buka di DB Browser for SQLite.

## Jalan otomatis gratis di GitHub Actions (laptop boleh mati)
File `.github/workflows/sinyal.yml` sudah disiapkan. Jadwalnya Senin–Jumat 18.47 WIB untuk scan, dan Jumat 20.13 WIB untuk rapor.
1. Buat repo baru di github.com. Repo **Public** gratis tanpa batas; Private dapat kuota 2.000 menit/bulan (agent ini cuma pakai ±2 menit sehari).
2. Upload semua isi folder ini, termasuk folder `.github`, **kecuali** `.env`.
3. Buka Settings → Secrets and variables → Actions:
   - Tab **Secrets**: isi `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, dan `ANTHROPIC_API_KEY` (opsional).
   - Tab **Variables** (opsional): `WATCHLIST`, `MODAL_RP`, `RISK_PCT`.
4. Buka tab Actions → Sinyal Saham IDX → **Run workflow** untuk mencoba sekarang.

Catatan:
- Secrets tetap rahasia walaupun repo-nya Public, tapi kode dan `signals.db` bisa dilihat orang lain.
- Saat hari libur bursa, jadwal otomatis tidak mengirim apa-apa (`SKIP_STALE`).
- Jurnal `signals.db` disimpan kembali ke repo setiap kali agent jalan.
- Di repo Public, jadwal dimatikan otomatis kalau repo tidak ada aktivitas selama 60 hari. Commit jurnal harian biasanya cukup sebagai aktivitas. Kalau jadwalnya mati, aktifkan lagi di tab Actions.

## Jadwal otomatis (cron, server WIB)
```
30 18 * * 1-5 cd /path/idx-signal-agent && /usr/bin/python3 main.py >> log.txt 2>&1
0 20 * * 5    cd /path/idx-signal-agent && /usr/bin/python3 main.py stats >> log.txt 2>&1
```
Kalau pakai GitHub Actions, file `signals.db` harus di-commit balik ke repo atau disimpan di luar (mis. Turso/Supabase). Kalau tidak, jurnal hilang setiap run.
Pilihan lain: GitHub Actions (cron UTC `30 11 * * 1-5`) atau workflow n8n.

## Pengembangan berikutnya
- Backtest aturan di data 2–3 tahun sebelum dipakai serius.
- Tambah tool untuk agent: berita emiten, data broker/asing.
- Simpan histori sinyal (CSV/SQLite) untuk mengukur winrate.

Ini alat bantu analisa, bukan rekomendasi investasi.
