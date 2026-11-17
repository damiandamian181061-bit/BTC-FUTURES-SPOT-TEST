"""
Read-only connection check for the Binance demo accounts (step 4, before any order code).
Places NO orders. Prints balances, fees, and the futures settings A needs.

Run inside WSL from the project folder:
  btc-bot connection-check
Exit code 0 = both accounts reachable and usable, 1 = something to fix (printed).
"""
import sys
from pathlib import Path
sys.dont_write_bytecode = True
from . import exchange as X

MAKER_ASSUMED, TAKER_ASSUMED = 0.0002, 0.0005     # backtest fee assumption per side (STRATEGY_RULES.md)


def check_spot(c, problems):
    print(f"\n=== B: spot demo ({c.base}) ===")
    off = c.sync_time(); print(f"clock offset vs Binance: {off:+d} ms" + ("  (large: sync Windows time)" if abs(off) > 1000 else ""))
    acct = c.get("/api/v3/account", {"omitZeroBalances": "true"}, signed=True)
    print(f"canTrade {acct.get('canTrade')} | canWithdraw {acct.get('canWithdraw')} | account type {acct.get('accountType')}")
    if not acct.get("canTrade"): problems.append("spot key cannot trade: enable 'Spot & Margin Trading' on btc-B-spot")
    bal = {b["asset"]: float(b["free"]) + float(b["locked"]) for b in acct.get("balances", [])}
    for a in ("USDT", "BTC", "USDC"):
        if a in bal: print(f"  {a:5s} {bal[a]:,.6f}")
    if bal.get("USDT", 0) <= 0: problems.append("spot demo has no USDT: reset/top up the demo balance in the Demo Trading UI")
    try:
        cm = c.get("/api/v3/account/commission", {"symbol": "BTCUSDT"}, signed=True)
        mk, tk = float(cm["standardCommission"]["maker"]), float(cm["standardCommission"]["taker"])
        print(f"BTCUSDT spot fees: maker {mk:.4%} | taker {tk:.4%}")
    except (X.ExchangeError, KeyError) as e:
        print(f"(fee lookup not available: {e})")
    px = c.get("/api/v3/ticker/price", {"symbol": "BTCUSDT"})["price"]
    print(f"BTCUSDT spot demo price: {float(px):,.2f}")


def check_futures(c, problems):
    print(f"\n=== A: USD-M futures demo ({c.base}) ===")
    off = c.sync_time(); print(f"clock offset vs Binance: {off:+d} ms" + ("  (large: sync Windows time)" if abs(off) > 1000 else ""))
    try:
        bal = c.get("/fapi/v3/balance", signed=True)
    except X.ExchangeError:
        bal = c.get("/fapi/v2/balance", signed=True)
    usdt = next((b for b in bal if b.get("asset") == "USDT"), None)
    if usdt:
        print(f"USDT wallet {float(usdt['balance']):,.2f} | available {float(usdt['availableBalance']):,.2f}")
    if not usdt or float(usdt["balance"]) <= 0: problems.append("futures demo has no USDT")
    dual = c.get("/fapi/v1/positionSide/dual", signed=True).get("dualSidePosition")
    print(f"position mode: {'HEDGE (two-sided)' if dual else 'ONE-WAY'}")
    if dual: problems.append("futures is in hedge mode: switch to one-way (A only ever holds one long). The bot can do this later.")
    try:
        pr = c.get("/fapi/v3/positionRisk", {"symbol": "BTCUSDT"}, signed=True)
    except X.ExchangeError:
        pr = c.get("/fapi/v2/positionRisk", {"symbol": "BTCUSDT"}, signed=True)
    for p in pr or []:
        amt = float(p.get("positionAmt", 0))
        print(f"BTCUSDT position {amt} | margin {p.get('marginType', 'n/a')} | leverage {p.get('leverage', 'n/a')}")
        if amt != 0: problems.append(f"open BTCUSDT futures position ({amt}): A should be flat outside 21:00-23:00")
    try:
        fee = c.get("/fapi/v1/commissionRate", {"symbol": "BTCUSDT"}, signed=True)
        mk, tk = float(fee["makerCommissionRate"]), float(fee["takerCommissionRate"])
        print(f"BTCUSDT futures fees: maker {mk:.4%} | taker {tk:.4%}  (backtest assumes {MAKER_ASSUMED:.2%} / {TAKER_ASSUMED:.2%})")
    except (X.ExchangeError, KeyError) as e:
        print(f"(fee lookup not available: {e})")
    pi = c.get("/fapi/v1/premiumIndex", {"symbol": "BTCUSDT"})
    print(f"BTCUSDT perp mark price {float(pi['markPrice']):,.2f} | funding rate {float(pi['lastFundingRate']):+.4%} per 8 h")
    bt = c.get("/fapi/v1/ticker/bookTicker", {"symbol": "BTCUSDT"})
    bid, ask = float(bt["bidPrice"]), float(bt["askPrice"])
    print(f"best bid {bid:,.2f} / ask {ask:,.2f} | spread {(ask - bid) / ((ask + bid) / 2) * 1e4:.2f} bp")


def main():
    print("Read-only check: no orders are placed.")
    try:
        sec, warns = X.load_secrets()
    except X.SecretsError as e:
        print("ERROR:", e); print("Put the four keys in .env (see .env.example) or in the secrets file, then retry."); return 1
    print(f"secrets: {X.LAST_SOURCE} | B key {X.mask(sec['B_SPOT_API_KEY'])} | A key {X.mask(sec['A_FUTURES_API_KEY'])}")
    for w in warns: print("WARNING:", w)
    problems = []
    for name, fn, client in (("B spot", check_spot, X.spot_client(sec)), ("A futures", check_futures, X.futures_client(sec))):
        try:
            fn(client, problems)
        except X.ExchangeError as e:
            problems.append(f"{name}: {e}")
            if e.code in (-2014, -2015, -1022):
                problems.append(f"{name}: key/secret rejected. Check you pasted the right pair (no spaces), and the key is a DEMO key")
    print()
    for p in problems: print("PROBLEM:", p)
    print("ALL OK: both demo accounts reachable." if not problems else f"{len(problems)} problem(s) to fix.")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
