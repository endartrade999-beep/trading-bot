"""
╔══════════════════════════════════════════════╗
║   🤖 AUTO TRADING BOT v4                    ║
║   Strategi : Harga vs EMA20                  ║
║   Timeframe: M1  |  Leverage: 20x            ║
║   Bybit Testnet  |  BTCUSDT                  ║
╚══════════════════════════════════════════════╝
"""

from pybit.unified_trading import HTTP
import time, csv, os
from datetime import datetime

API_KEY    = "gGRlsiVOpPHAtwGK5s"
API_SECRET = "bYBBsNvANys3M7WjYapRxzAKGkRepUGz6pNq"

PAIR       = "BTCUSDT"
LEVERAGE   = 20
MARGIN_USD = 100
SL_PERSEN  = 1.5
TP_PERSEN  = 3.0
EMA_PERIOD = 20
TF         = "1"    # M1
INTERVAL   = 10     # cek tiap 10 detik
LOG_FILE   = "trade_log.csv"

session = HTTP(testnet=True, api_key=API_KEY, api_secret=API_SECRET)

def log(msg):
    print(f"[{datetime.now().strftime('%d/%m %H:%M:%S')}] {msg}")

def cek_saldo():
    try:
        r = session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
        coins = r["result"]["list"][0]["coin"]
        usdt = next((c for c in coins if c["coin"] == "USDT"), None)
        return float(usdt["walletBalance"]) if usdt else 0
    except:
        return 0

def ambil_candles(limit=50):
    try:
        r = session.get_kline(category="linear", symbol=PAIR, interval=TF, limit=limit)
        return [float(c[4]) for c in reversed(r["result"]["list"])]
    except Exception as e:
        log(f"❌ Gagal ambil candle: {e}")
        return []

def hitung_ema(data, period):
    if len(data) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(data[:period]) / period
    for price in data[period:]:
        ema = price * k + ema * (1 - k)
    return ema

def get_sinyal(closes):
    if len(closes) < EMA_PERIOD + 2:
        return None, None
    ema_now  = hitung_ema(closes, EMA_PERIOD)
    ema_prev = hitung_ema(closes[:-1], EMA_PERIOD)
    harga_now  = closes[-1]
    harga_prev = closes[-2]
    if None in [ema_now, ema_prev]:
        return None, ema_now
    # Cross ke atas EMA20 → LONG
    if harga_prev <= ema_prev and harga_now > ema_now:
        return "LONG", ema_now
    # Cross ke bawah EMA20 → SHORT
    if harga_prev >= ema_prev and harga_now < ema_now:
        return "SHORT", ema_now
    return None, ema_now

def get_posisi_aktif():
    try:
        r = session.get_positions(category="linear", symbol=PAIR)
        for p in r["result"]["list"]:
            if float(p["size"]) > 0:
                return p
        return None
    except:
        return None

def tutup_posisi(posisi):
    try:
        close_side = "Sell" if posisi["side"] == "Buy" else "Buy"
        session.place_order(
            category="linear", symbol=PAIR,
            side=close_side, orderType="Market",
            qty=posisi["size"], reduceOnly=True, timeInForce="GTC",
        )
        pnl = float(posisi["unrealisedPnl"])
        log(f"{'✅' if pnl >= 0 else '❌'} Posisi DITUTUP | PnL: ${pnl:+,.2f}")
    except Exception as e:
        log(f"❌ Gagal tutup: {e}")

def get_qty(harga):
    try:
        r = session.get_instruments_info(category="linear", symbol=PAIR)
        info = r["result"]["list"][0]["lotSizeFilter"]
        min_qty  = float(info["minOrderQty"])
        qty_step = float(info["qtyStep"])
        qty = round(round((MARGIN_USD * LEVERAGE / harga) / qty_step) * qty_step, 10)
        return max(qty, min_qty)
    except:
        return 0.001

def buka_posisi(direction, harga):
    try:
        session.set_leverage(
            category="linear", symbol=PAIR,
            buyLeverage=str(LEVERAGE), sellLeverage=str(LEVERAGE)
        )
    except:
        pass

    side = "Buy" if direction == "LONG" else "Sell"
    qty  = get_qty(harga)

    if direction == "LONG":
        sl = round(harga * (1 - SL_PERSEN / 100), 2)
        tp = round(harga * (1 + TP_PERSEN / 100), 2)
    else:
        sl = round(harga * (1 + SL_PERSEN / 100), 2)
        tp = round(harga * (1 - TP_PERSEN / 100), 2)

    try:
        r = session.place_order(
            category="linear", symbol=PAIR,
            side=side, orderType="Market",
            qty=str(qty), stopLoss=str(sl),
            takeProfit=str(tp), timeInForce="GTC",
        )
        if r["retCode"] == 0:
            log(f"🚀 {direction} DIBUKA! Entry: ${harga:,.2f} | SL: ${sl:,.2f} | TP: ${tp:,.2f} | Qty: {qty} | 20x")
            file_baru = not os.path.exists(LOG_FILE)
            with open(LOG_FILE, "a", newline="") as f:
                w = csv.writer(f)
                if file_baru:
                    w.writerow(["Waktu","Pair","Direction","Entry","SL","TP","Qty","Leverage","Margin"])
                w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            PAIR, direction, harga, sl, tp, qty, LEVERAGE, MARGIN_USD])
        else:
            log(f"❌ Order gagal: {r['retMsg']}")
    except Exception as e:
        log(f"❌ Error: {e}")

def jalankan_bot():
    os.system('cls' if os.name == 'nt' else 'clear')
    print("""
╔══════════════════════════════════════════════╗
║   🤖 AUTO BOT v4 — HARGA vs EMA20           ║
║   Pair     : BTCUSDT  | TF    : M1          ║
║   Leverage : 20x      | Margin: $100/trade  ║
║   SL: 1.5% | TP: 3%  | RR   : 1:2         ║
║   Tekan Ctrl+C untuk stop                   ║
╚══════════════════════════════════════════════╝
""")

    saldo = cek_saldo()
    log(f"💰 Saldo: ${saldo:,.2f} USDT")

    if saldo < MARGIN_USD:
        log(f"⚠️  Saldo kurang! Transfer dana ke Unified Trading dulu.")
        return

    log(f"✅ Bot aktif! Cek sinyal tiap {INTERVAL} detik di M1...")
    log("─" * 55)

    while True:
        try:
            closes = ambil_candles(limit=50)
            if not closes:
                time.sleep(INTERVAL)
                continue

            harga        = closes[-1]
            sinyal, ema  = get_sinyal(closes)
            posisi       = get_posisi_aktif()

            if posisi:
                arah    = "🟢 LONG" if posisi["side"] == "Buy" else "🔴 SHORT"
                pnl     = float(posisi["unrealisedPnl"])
                pnl_str = f"| PnL: ${pnl:+,.2f}"
            else:
                arah    = "⬜ IDLE"
                pnl_str = ""

            ema_str = f"{ema:,.1f}" if ema else "—"
            log(f"💹 ${harga:,.2f} | EMA20: {ema_str} | {arah} {pnl_str} | Sinyal: {sinyal or '—'}")

            if sinyal:
                if posisi:
                    arah_posisi = "LONG" if posisi["side"] == "Buy" else "SHORT"
                    if arah_posisi != sinyal:
                        log(f"🔄 Balik arah! Tutup {arah_posisi} → Buka {sinyal}")
                        tutup_posisi(posisi)
                        time.sleep(2)
                        harga_baru = ambil_candles(limit=5)[-1]
                        buka_posisi(sinyal, harga_baru)
                    else:
                        log(f"ℹ️  {arah_posisi} sudah ada, skip.")
                else:
                    log(f"📡 Sinyal {sinyal}! Eksekusi...")
                    buka_posisi(sinyal, harga)

            time.sleep(INTERVAL)

        except KeyboardInterrupt:
            print("\n")
            log("⛔ Bot dihentikan.")
            posisi = get_posisi_aktif()
            if posisi:
                jawab = input("   Tutup posisi yang terbuka? (y/n): ").strip().lower()
                if jawab == 'y':
                    tutup_posisi(posisi)
            log(f"💰 Saldo akhir: ${cek_saldo():,.2f}")
            break

        except Exception as e:
            log(f"⚠️ Error: {e} — retry {INTERVAL}s...")
            time.sleep(INTERVAL)

if __name__ == "__main__":
    jalankan_bot()
