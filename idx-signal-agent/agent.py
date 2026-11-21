"""Agent AI: meninjau kandidat sinyal, boleh minta detail saham, lalu memilih
dan memberi komentar. AI TIDAK boleh mengubah angka entry/SL/TP;
angka selalu diambil dari hasil kode (signals.py)."""
import json
import anthropic
import config

SYSTEM = """Kamu analis teknikal saham IDX yang memakai kaidah komunitas HQSaham.
Kamu menerima kandidat sinyal (id = KODE:TIPE) yang dihitung sistem dari data OHLCV.
Jenis sinyal: VP_VAL_BOUNCE, VP_VAH_BREAKOUT (Volume Profile), FR4_BREAKOUT,
FR2_PULLBACK (fractal), FCAAK (squeeze + bullish divergence + spike + area bottom),
MA_GC (golden cross MA20/50), STATS_REV (pantul dari low 52 minggu), BB_BOUNCE, GZ_FIBO, HBO_VOL, BPJS (kandidat
beli pagi jual sore besok).

Kaidah yang harus kamu pegang:
- Jangan entri di sekitar POC (gerak acak). Breakout VAH/fractal wajib didukung volume.
- Fractal selalu terlambat beberapa candle; segitiga fractal bukan "beli di sini".
- Spike volume = mulai diawasi, bukan otomatis beli.
- FCAAK itu swing yang butuh sabar; sinyal yang dekat upper band atau jauh di atas mid BB tidak cocok.
- Lebih banyak indikator tidak berarti lebih akurat; screener bagus = output sedikit.
- Data bandar/asing/frekuensi/bid-offer TIDAK tersedia di sistem ini; jangan mengarang.
  Kalau keputusannya bergantung pada itu, sebutkan bahwa perlu dicek di @HQSahamIDX_bot.

Tugas:
1. Tinjau kandidat. Pakai get_stock_detail bila perlu konteks (filter yang lolos, MA, RSI, fractal, VP).
2. Buang yang meragukan (mis. RSI > 75 untuk sinyal beli, sinyal beli di bawah MA50 tanpa
   alasan reversal, beberapa sinyal saling bertentangan di saham yang sama).
3. Panggil submit_report SEKALI: id yang lolos (maks {max}) + komentar maks 2 kalimat
   Bahasa Indonesia per id, plus ringkasan 1 kalimat.
Jangan menulis angka harga baru. Ini bahan analisa, bukan rekomendasi beli/jual."""

TOOLS = [
    {
        "name": "get_stock_detail",
        "description": "Detail indikator saham: filter yang lolos, POC/VAH/VAL, fractal merah/hijau, RSI, MA20/50, volume, nilai transaksi.",
        "input_schema": {"type": "object", "properties": {"kode": {"type": "string"}}, "required": ["kode"]},
    },
    {
        "name": "submit_report",
        "description": "Kirim hasil akhir. Hanya id dari daftar kandidat yang diterima.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ringkasan": {"type": "string"},
                "picks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"id": {"type": "string"}, "komentar": {"type": "string"}},
                        "required": ["id", "komentar"],
                    },
                },
            },
            "required": ["ringkasan", "picks"],
        },
    },
]


def review(candidates: list[dict], all_info: dict[str, dict], max_turns: int = 10) -> dict | None:
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    ringkas = [{"id": c["id"], "kode": c["kode"], "tipe": c["signal"]["tipe"],
                "skor": c["signal"]["skor"], "alasan": c["signal"]["alasan"],
                "close": c["close"], "chg_pct": c["chg_pct"], "rsi": c["rsi"],
                "entry": c["signal"]["entry"], "sl": c["signal"]["sl"],
                "tp1": c["signal"]["tp1"], "rr": c["signal"]["rr"]} for c in candidates]
    messages = [{"role": "user", "content": "Kandidat sinyal hari ini:\n" + json.dumps(ringkas, ensure_ascii=False, indent=1)}]
    system = SYSTEM.replace("{max}", str(config.MAX_SIGNALS))
    for _ in range(max_turns):
        resp = client.messages.create(model=config.ANTHROPIC_MODEL, max_tokens=3000,
                                      system=system, tools=TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            if block.name == "submit_report":
                return block.input
            if block.name == "get_stock_detail":
                kode = block.input.get("kode", "").upper()
                data = all_info.get(kode, {"error": "kode tidak ada di watchlist"})
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": json.dumps(data, ensure_ascii=False, default=str)})
        if not results:
            break
        messages.append({"role": "user", "content": results})
    return None
