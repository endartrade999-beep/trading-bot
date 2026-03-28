"""
╔══════════════════════════════════════════════════════╗
║   🤖 AL BROOKS BOT — PARTIAL TP + BREAKEVEN SL     ║
║                                                      ║
║   FLOW:                                              ║
║   1. Entry → SL 1% di bawah/atas entry              ║
║   2. Harga hit TP1 (1.25%) → close 50%              ║
║      → SL dipindah ke ENTRY (breakeven)             ║
║   3. Harga hit TP2 (3%) → close sisa 50%            ║
║                                                      ║
║   Bybit Demo Trading | BTCUSDT | M15 | 40x          ║
╚══════════════════════════════════════════════════════╝
"""

import requests, hmac, hashlib, time, csv, os
from datetime import datetime

# ══════════════════════════════════════════════
API_KEY    = "rfN7mxutHZXKrW5CM5"
API_SECRET = "3aeagSHENrmenbXvBj5g4XtD5HMLj6u9kv0Z"

BASE_URL     = "https://api-demo.bybit.com"
PAIR         = "BTCUSDT"
LEVERAGE     = 40
MARGIN_USD   = 100
SL_PERSEN    = 1.0
TP1_PERSEN   = 1.25
TP2_PERSEN   = 3.0
EMA_PERIOD   = 20
TF           = "15"
INTERVAL     = 30
LOG_FILE     = "partial_tp_log.csv"
STRONG_BAR_MIN = 0.65
KONFIRMASI_MIN = 2

posisi_state = {
    "active": False, "direction": None, "entry": 0,
    "tp1": 0, "tp2": 0, "tp1_done": False, "be_done": False,
}

# ── HTTP HELPER ───────────────────────────────

def get_request(endpoint, params=None):
    if params is None: params = {}
    ts  = str(int(time.time() * 1000))
    rw  = "5000"
    q   = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
    sig = hmac.new(API_SECRET.encode(), (ts+API_KEY+rw+q).encode(), hashlib.sha256).hexdigest()
    h   = {"X-BAPI-API-KEY": API_KEY, "X-BAPI-TIMESTAMP": ts, "X-BAPI-SIGN": sig, "X-BAPI-RECV-WINDOW": rw}
    return requests.get(f"{BASE_URL}{endpoint}", params=params, headers=h).json()

def post_request(endpoint, body):
    import json
    ts      = str(int(time.time() * 1000))
    rw      = "5000"
    bs      = json.dumps(body, separators=(',', ':'))
    sig     = hmac.new(API_SECRET.encode(), (ts+API_KEY+rw+bs).encode(), hashlib.sha256).hexdigest()
    h       = {"X-BAPI-API-KEY": API_KEY, "X-BAPI-TIMESTAMP": ts, "X-BAPI-SIGN": sig,
               "X-BAPI-RECV-WINDOW": rw, "Content-Type": "application/json"}
    return requests.post(f"{BASE_URL}{endpoint}", data=bs, headers=h).json()

# ── FUNGSI TRADING ────────────────────────────

def log(msg): print(f"[{datetime.now().strftime('%d/%m %H:%M:%S')}] {msg}")

def cek_saldo():
    try:
        r = get_request("/v5/account/wallet-balance", {"accountType": "UNIFIED", "coin": "USDT"})
        coins = r["result"]["list"][0]["coin"]
        usdt  = next((c for c in coins if c["coin"] == "USDT"), None)
        return float(usdt["walletBalance"]) if usdt else 0
    except: return 0

def ambil_candles(limit=100):
    try:
        r = get_request("/v5/market/kline", {"category": "linear", "symbol": PAIR, "interval": TF, "limit": limit})
        return [{"open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4]), "volume": float(c[5])}
                for c in reversed(r["result"]["list"])]
    except Exception as e:
        log(f"❌ Candle: {e}"); return []

def get_qty_step():
    try:
        r    = get_request("/v5/market/instruments-info", {"category": "linear", "symbol": PAIR})
        info = r["result"]["list"][0]["lotSizeFilter"]
        return float(info["minOrderQty"]), float(info["qtyStep"])
    except: return 0.001, 0.001

def get_qty(harga):
    mq, qs = get_qty_step()
    return max(round(round((MARGIN_USD * LEVERAGE / harga) / qs) * qs, 10), mq)

def round_qty(qty):
    _, qs = get_qty_step()
    return round(round(qty / qs) * qs, 10)

def get_posisi_aktif():
    try:
        r = get_request("/v5/position/list", {"category": "linear", "symbol": PAIR})
        for p in r["result"]["list"]:
            if float(p["size"]) > 0: return p
        return None
    except: return None

def reset_state():
    global posisi_state
    posisi_state = {"active": False, "direction": None, "entry": 0,
                    "tp1": 0, "tp2": 0, "tp1_done": False, "be_done": False}

def pindah_sl_breakeven(entry, direction):
    """Pindah SL ke entry (breakeven) + buffer fee kecil"""
    try:
        be = round(entry * 1.001, 2) if direction == "LONG" else round(entry * 0.999, 2)
        r  = post_request("/v5/position/trading-stop", {
            "category": "linear", "symbol": PAIR,
            "stopLoss": str(be), "positionIdx": 0
        })
        if r["retCode"] == 0:
            log(f"🔒 SL → BREAKEVEN ${be:,.2f} | Trade ini RISK FREE! 🎉")
            return True
        else:
            log(f"⚠️ Gagal pindah SL: {r['retMsg']}"); return False
    except Exception as e:
        log(f"❌ Error SL: {e}"); return False

def partial_close_50(posisi):
    """Close 50% posisi"""
    try:
        size  = float(posisi["size"])
        close = round_qty(size * 0.5)
        _, qs = get_qty_step()
        close = max(close, qs)
        close = min(close, size)
        side  = "Sell" if posisi["side"] == "Buy" else "Buy"
        r     = post_request("/v5/order/create", {
            "category": "linear", "symbol": PAIR, "side": side,
            "orderType": "Market", "qty": str(close),
            "reduceOnly": True, "timeInForce": "GTC"
        })
        if r["retCode"] == 0:
            pnl = float(posisi["unrealisedPnl"]) * 0.5
            log(f"✅ TP1 HIT! Close 50% | Est PnL: ${pnl:+,.2f} | Sisa: ~{round(size-close,3)}")
            return True
        else:
            log(f"❌ Partial gagal: {r['retMsg']}"); return False
    except Exception as e:
        log(f"❌ Error partial: {e}"); return False

def tutup_semua(posisi):
    try:
        side = "Sell" if posisi["side"] == "Buy" else "Buy"
        r    = post_request("/v5/order/create", {
            "category": "linear", "symbol": PAIR, "side": side,
            "orderType": "Market", "qty": posisi["size"],
            "reduceOnly": True, "timeInForce": "GTC"
        })
        pnl = float(posisi["unrealisedPnl"])
        log(f"{'✅ PROFIT' if pnl >= 0 else '❌ LOSS'} TP2 HIT! Semua ditutup | PnL: ${pnl:+,.2f}")
        reset_state()
    except Exception as e:
        log(f"❌ Error tutup: {e}")

def buka_posisi(direction, harga, alasan):
    try:
        post_request("/v5/position/set-leverage", {
            "category": "linear", "symbol": PAIR,
            "buyLeverage": str(LEVERAGE), "sellLeverage": str(LEVERAGE)
        })
    except: pass

    side = "Buy" if direction == "LONG" else "Sell"
    qty  = get_qty(harga)

    if direction == "LONG":
        sl  = round(harga * (1 - SL_PERSEN  / 100), 2)
        tp1 = round(harga * (1 + TP1_PERSEN / 100), 2)
        tp2 = round(harga * (1 + TP2_PERSEN / 100), 2)
    else:
        sl  = round(harga * (1 + SL_PERSEN  / 100), 2)
        tp1 = round(harga * (1 - TP1_PERSEN / 100), 2)
        tp2 = round(harga * (1 - TP2_PERSEN / 100), 2)

    r = post_request("/v5/order/create", {
        "category": "linear", "symbol": PAIR, "side": side,
        "orderType": "Market", "qty": str(qty),
        "stopLoss": str(sl), "timeInForce": "GTC"
    })

    if r["retCode"] == 0:
        log(f"🚀 {direction} DIBUKA!")
        log(f"   Entry : ${harga:,.2f}")
        log(f"   SL    : ${sl:,.2f}  (-{SL_PERSEN}%)")
        log(f"   TP1   : ${tp1:,.2f} (+{TP1_PERSEN}%) → close 50% + SL ke entry")
        log(f"   TP2   : ${tp2:,.2f} (+{TP2_PERSEN}%) → close 50% sisa")
        log(f"   Setup : {alasan} | {LEVERAGE}x | Qty: {qty}")
        posisi_state.update({"active": True, "direction": direction, "entry": harga,
                             "tp1": tp1, "tp2": tp2, "tp1_done": False, "be_done": False})
        file_baru = not os.path.exists(LOG_FILE)
        with open(LOG_FILE, "a", newline="") as f:
            w = csv.writer(f)
            if file_baru:
                w.writerow(["Waktu","Pair","Direction","Setup","Entry","SL","TP1","TP2","Qty","Leverage"])
            w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        PAIR, direction, alasan, harga, sl, tp1, tp2, qty, LEVERAGE])
    else:
        log(f"❌ Gagal: {r['retMsg']}")

def monitor_tp(posisi, harga):
    if not posisi_state["active"]: return
    d, tp1, tp2 = posisi_state["direction"], posisi_state["tp1"], posisi_state["tp2"]
    done = posisi_state["tp1_done"]

    if d == "LONG":
        if not done and harga >= tp1:
            log(f"🎯 TP1! ${harga:,.2f} >= ${tp1:,.2f}")
            if partial_close_50(posisi):
                posisi_state["tp1_done"] = True
                pindah_sl_breakeven(posisi_state["entry"], d)
                posisi_state["be_done"] = True
                log(f"   Nunggu TP2 di ${tp2:,.2f}...")
        elif done and harga >= tp2:
            log(f"🎯 TP2! ${harga:,.2f} >= ${tp2:,.2f}")
            tutup_semua(posisi)

    elif d == "SHORT":
        if not done and harga <= tp1:
            log(f"🎯 TP1! ${harga:,.2f} <= ${tp1:,.2f}")
            if partial_close_50(posisi):
                posisi_state["tp1_done"] = True
                pindah_sl_breakeven(posisi_state["entry"], d)
                posisi_state["be_done"] = True
                log(f"   Nunggu TP2 di ${tp2:,.2f}...")
        elif done and harga <= tp2:
            log(f"🎯 TP2! ${harga:,.2f} <= ${tp2:,.2f}")
            tutup_semua(posisi)

# ── AL BROOKS STRATEGY ────────────────────────

def hitung_ema(closes, period):
    if len(closes) < period: return None
    k = 2 / (period + 1)
    e = sum(closes[:period]) / period
    for p in closes[period:]: e = p * k + e * (1 - k)
    return e

def body_r(c):
    t = c["high"] - c["low"]
    return 0 if t == 0 else abs(c["close"] - c["open"]) / t

def close_p(c):
    t = c["high"] - c["low"]
    return 0.5 if t == 0 else (c["close"] - c["low"]) / t

def is_bull(c): return c["close"] > c["open"] and body_r(c) >= STRONG_BAR_MIN and close_p(c) >= 0.65
def is_bear(c): return c["close"] < c["open"] and body_r(c) >= STRONG_BAR_MIN and close_p(c) <= 0.35

def cek_trend_bar(candles, trend, ema):
    if len(candles) < 3: return None, ""
    last, prev = candles[-1], candles[-2]
    if trend == "UP" and is_bull(last) and not is_bull(prev):
        conf = sum([True, last["close"] > ema, abs(last["low"]-ema)/ema < 0.02])
        if conf >= KONFIRMASI_MIN: return "LONG", f"WithTrend-Bull({conf}/3)"
    if trend == "DOWN" and is_bear(last) and not is_bear(prev):
        conf = sum([True, last["close"] < ema, abs(last["high"]-ema)/ema < 0.02])
        if conf >= KONFIRMASI_MIN: return "SHORT", f"WithTrend-Bear({conf}/3)"
    return None, ""

def cek_fb(candles, trend):
    if len(candles) < 8: return None, ""
    lb = candles[-8:-2]; prev, last = candles[-2], candles[-1]
    rh = max(c["high"] for c in lb); rl = min(c["low"] for c in lb)
    if prev["high"] > rh and last["close"] < rh and is_bear(last) and trend == "DOWN":
        conf = sum([True, is_bear(last), last["close"] < prev["open"]])
        if conf >= KONFIRMASI_MIN: return "SHORT", f"FailedBreakout→SHORT({conf}/3)"
    if prev["low"] < rl and last["close"] > rl and is_bull(last) and trend == "UP":
        conf = sum([True, is_bull(last), last["close"] > prev["open"]])
        if conf >= KONFIRMASI_MIN: return "LONG", f"FailedBreakout→LONG({conf}/3)"
    return None, ""

def cek_2leg(candles, trend, ema):
    if len(candles) < 15: return None, ""
    last = candles[-1]
    if trend == "UP":
        l1 = min(c["low"]  for c in candles[-10:-5])
        l2 = min(c["low"]  for c in candles[-5:-1])
        if l2 > l1 * 0.998 and is_bull(last):
            conf = sum([l2 > l1*0.998, is_bull(last), min(l1,l2) > ema*0.97])
            if conf >= KONFIRMASI_MIN: return "LONG", f"2LegPullback-UP({conf}/3)"
    elif trend == "DOWN":
        h1 = max(c["high"] for c in candles[-10:-5])
        h2 = max(c["high"] for c in candles[-5:-1])
        if h2 < h1 * 1.002 and is_bear(last):
            conf = sum([h2 < h1*1.002, is_bear(last), max(h1,h2) < ema*1.03])
            if conf >= KONFIRMASI_MIN: return "SHORT", f"2LegPullback-DOWN({conf}/3)"
    return None, ""

def get_sinyal(candles):
    if len(candles) < EMA_PERIOD + 10: return None, None, ""
    closes = [c["close"] for c in candles]
    ema    = hitung_ema(closes, EMA_PERIOD)
    if not ema: return None, None, ""
    trend = "UP" if candles[-1]["close"] > ema else "DOWN"
    for fn in [(cek_2leg, [candles,trend,ema]), (cek_fb, [candles,trend]), (cek_trend_bar, [candles,trend,ema])]:
        s, a = fn[0](*fn[1])
        if s: return s, ema, a
    return None, ema, ""

# ── MAIN LOOP ─────────────────────────────────

def jalankan_bot():
    os.system('cls' if os.name == 'nt' else 'clear')
    print("""
╔══════════════════════════════════════════════════════╗
║   🤖 AL BROOKS — PARTIAL TP + BREAKEVEN SL         ║
║   Pair: BTCUSDT | TF: M15 | Leverage: 40x          ║
║   SL: 1% | TP1: 1.25%(50%) | TP2: 3%(50%)         ║
║                                                      ║
║   FLOW: Entry → TP1 hit → Close 50% + SL ke Entry  ║
║              → TP2 hit → Close 50% sisa → Done! ✅ ║
╚══════════════════════════════════════════════════════╝
""")
    saldo = cek_saldo()
    log(f"💰 Saldo Demo: ${saldo:,.2f} USDT")
    if saldo < MARGIN_USD:
        log("⚠️  Saldo kurang! Klik 'Request Demo Funds' di Bybit."); return

    log(f"✅ Bot aktif! Partial TP + Breakeven running...")
    log("─" * 55)

    while True:
        try:
            candles = ambil_candles(100)
            if not candles: time.sleep(INTERVAL); continue

            harga               = candles[-1]["close"]
            sinyal, ema, alasan = get_sinyal(candles)
            posisi              = get_posisi_aktif()

            if not posisi and posisi_state["active"]:
                log("ℹ️  Posisi sudah tertutup (SL/TP kena)"); reset_state()

            trend = "📈 UP" if ema and harga > ema else "📉 DOWN"

            if posisi:
                pnl      = float(posisi["unrealisedPnl"])
                arah     = "🟢 LONG" if posisi["side"] == "Buy" else "🔴 SHORT"
                tp1_info = "✅TP1done+BE🔒" if posisi_state["tp1_done"] else f"⏳TP1@${posisi_state['tp1']:,.0f}"
                log(f"💹 ${harga:,.2f} | EMA:{ema:,.0f} | {trend} | {arah} PnL:${pnl:+,.2f} | {tp1_info}")
                monitor_tp(posisi, harga)
            else:
                log(f"💹 ${harga:,.2f} | EMA:{ema:,.0f} | {trend} | ⬜ IDLE | {alasan or '—'}")
                if sinyal:
                    log(f"🎯 SETUP: {alasan}")
                    buka_posisi(sinyal, harga, alasan)

            time.sleep(INTERVAL)

        except KeyboardInterrupt:
            print("\n"); log("⛔ Bot dihentikan.")
            posisi = get_posisi_aktif()
            if posisi and input("   Tutup posisi? (y/n): ").strip().lower() == 'y':
                tutup_semua(posisi)
            log(f"💰 Saldo: ${cek_saldo():,.2f} | Log: {LOG_FILE}"); break

        except Exception as e:
            log(f"⚠️ Error: {e}"); time.sleep(INTERVAL)

if __name__ == "__main__":
    jalankan_bot()
