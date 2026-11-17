"""
Order helpers for the paper-trading harness (step 4), built on exchange.BinanceClient.

One set of functions serves both venues; the client knows whether it is spot (B) or USD-M futures (A):
  filters    load_filters(c)                tick size, step size, min qty, min notional from exchangeInfo
  books      book(c), real_book(futures)    best bid/ask on the demo venue and on the REAL public Binance book
  balances   spot_equity(c), futures_account(c), futures_position(c), funding_paid(c, start_ms, end_ms)
  setup      futures_setup(c, leverage)     one-way mode + ISOLATED margin + leverage for BTCUSDT (A, once)
  orders     place_limit, place_market, get_order, cancel, cancel_all, open_orders, fills_for
  loops      work_order(...)                keep a post-only order at the touch until filled or a deadline
             market_rest(...)               close what is left at market (A's 23:00 fallback, B's ~15-min fallback)

Post-only on Binance: futures = LIMIT with timeInForce GTX ("good till crossing"); an order that would cross the
spread comes back with status EXPIRED and no fill. Spot = order type LIMIT_MAKER; one that would cross is rejected
with error -2010 "Order would immediately match and take". work_order() treats both as "the touch moved, read the
book again". Nothing here decides WHETHER to trade (that is signals.py + harness.py). Everything returns plain dicts
so ledger.py can log them. Quantities are BTC, prices USDT, times are ISO UTC strings.
"""
import os, sys, time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from pathlib import Path
from . import exchange as X

SYMBOL = "BTCUSDT"
REAL_FUTURES_URL = os.environ.get("BTC_BOT_REAL_FUTURES_URL", "https://fapi.binance.com")
REAL_SPOT_URL = os.environ.get("BTC_BOT_REAL_SPOT_URL", "https://data-api.binance.vision")
OPEN_STATES = ("NEW", "PARTIALLY_FILLED")
DONE_STATES = ("FILLED", "CANCELED", "EXPIRED", "REJECTED", "EXPIRED_IN_MATCH")


def iso(t=None):
    """ISO UTC timestamp (seconds) for a float epoch, default now."""
    return datetime.fromtimestamp(time.time() if t is None else t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _v(c): return "v1" if c.futures else "v3"


# ---------------------------------------------------------------- exchange filters
class Filters:
    """Rounding rules for one symbol. BUY prices round down, SELL prices round up: never more aggressive than asked."""
    def __init__(self, tick, step, min_qty, min_notional):
        self.tick, self.step, self.min_qty, self.min_notional = (Decimal(str(x)) for x in (tick, step, min_qty, min_notional))

    def price(self, p, side):
        return float((Decimal(str(p)) / self.tick).to_integral_value(rounding=ROUND_DOWN if side == "BUY" else ROUND_UP) * self.tick)

    def qty(self, q):
        return float((Decimal(str(max(q, 0))) / self.step).to_integral_value(rounding=ROUND_DOWN) * self.step)

    def fmt_price(self, p): return format(Decimal(str(p)).quantize(self.tick), "f")
    def fmt_qty(self, q): return format(Decimal(str(q)).quantize(self.step), "f")

    def too_small(self, qty, price):
        """Reason the order cannot be sent, or None."""
        if Decimal(str(qty)) < self.min_qty or qty <= 0: return f"qty {qty} below min qty {self.min_qty}"
        if Decimal(str(qty)) * Decimal(str(price)) < self.min_notional: return f"notional {qty * price:.2f} below min {self.min_notional}"
        return None

    def __repr__(self): return f"Filters(tick={self.tick}, step={self.step}, min_qty={self.min_qty}, min_notional={self.min_notional})"


def load_filters(c, symbol=SYMBOL):
    info = c.get(f"{c.prefix}/{_v(c)}/exchangeInfo", None if c.futures else {"symbol": symbol})
    s = next(x for x in info["symbols"] if x["symbol"] == symbol)
    f = {x["filterType"]: x for x in s["filters"]}
    n = f.get("MIN_NOTIONAL") or f.get("NOTIONAL") or {}
    return Filters(f["PRICE_FILTER"]["tickSize"], f["LOT_SIZE"]["stepSize"], f["LOT_SIZE"]["minQty"],
                   n.get("notional", n.get("minNotional", "0")))


# ---------------------------------------------------------------- prices and books
def book(c, symbol=SYMBOL):
    t = c.get(f"{c.prefix}/{_v(c)}/ticker/bookTicker", {"symbol": symbol})
    bid, ask = float(t["bidPrice"]), float(t["askPrice"])
    mid = (bid + ask) / 2
    return {"bid": bid, "ask": ask, "mid": mid, "spread_bp": (ask - bid) / mid * 1e4, "ts": iso()}


def real_client(futures):
    """Unsigned client for the REAL public Binance book (demo market data is only 'realistic')."""
    return X.BinanceClient(REAL_FUTURES_URL if futures else REAL_SPOT_URL, futures=futures, timeout=8)


def real_book(futures, symbol=SYMBOL):
    """Real best bid/ask, or None if the public host cannot be reached (never blocks trading)."""
    try:
        return book(real_client(futures), symbol)
    except X.ExchangeError:
        return None


def last_price(c, symbol=SYMBOL):
    return float(c.get(f"{c.prefix}/{_v(c)}/ticker/price", {"symbol": symbol})["price"])


def premium(c, symbol=SYMBOL):
    p = c.get("/fapi/v1/premiumIndex", {"symbol": symbol})
    return {"mark": float(p["markPrice"]), "funding_rate": float(p["lastFundingRate"]), "next_funding_ms": int(p.get("nextFundingTime", 0))}


def slippage_bp(side, fill_price, ref_mid):
    """Basis points paid versus a reference mid. Positive = worse than mid, negative = better (maker fills usually are)."""
    if not ref_mid or not fill_price: return None
    return ((fill_price - ref_mid) if side == "BUY" else (ref_mid - fill_price)) / ref_mid * 1e4


# ---------------------------------------------------------------- balances
def spot_balances(c):
    a = c.get("/api/v3/account", {"omitZeroBalances": "true"}, signed=True)
    return {b["asset"]: {"free": float(b["free"]), "locked": float(b["locked"])} for b in a.get("balances", [])}


def spot_equity(c, price=None):
    """USDT + BTC at the given (or last) price. Other assets in the demo account are ignored on purpose."""
    bal = spot_balances(c)
    price = price or last_price(c)
    btc, usdt = bal.get("BTC", {}), bal.get("USDT", {})
    b, u = btc.get("free", 0) + btc.get("locked", 0), usdt.get("free", 0) + usdt.get("locked", 0)
    return {"equity": u + b * price, "btc": b, "btc_free": btc.get("free", 0), "usdt": u, "usdt_free": usdt.get("free", 0), "price": price}


def futures_account(c):
    try:
        a = c.get("/fapi/v3/account", signed=True)
    except X.ExchangeError:
        a = c.get("/fapi/v2/account", signed=True)
    return {"wallet": float(a["totalWalletBalance"]), "unrealized": float(a.get("totalUnrealizedProfit", 0)),
            "equity": float(a.get("totalMarginBalance", a["totalWalletBalance"])), "available": float(a.get("availableBalance", 0))}


def futures_position(c, symbol=SYMBOL):
    """Current BTCUSDT position (one-way mode). qty > 0 long, 0 flat. leverage/margin_type may be None on v3."""
    out = {"qty": 0.0, "entry": 0.0, "unrealized": 0.0, "leverage": None, "margin_type": None}
    for v in ("v2", "v3"):                     # v2 still reports leverage + marginType; v3 may not
        try:
            rows = c.get(f"/fapi/{v}/positionRisk", {"symbol": symbol}, signed=True)
        except X.ExchangeError:
            continue
        p = next((x for x in rows if x.get("symbol") == symbol), None)
        if p is None: return out
        out.update(qty=float(p.get("positionAmt", 0)), entry=float(p.get("entryPrice", 0) or 0), unrealized=float(p.get("unRealizedProfit", 0) or 0))
        if p.get("leverage"): out["leverage"] = int(float(p["leverage"]))
        if p.get("marginType"): out["margin_type"] = str(p["marginType"]).upper()
        return out
    raise X.ExchangeError("positionRisk unavailable (v2 and v3)")


def funding_paid(c, start_ms, end_ms, symbol=SYMBOL):
    """Sum of FUNDING_FEE income in [start_ms, end_ms] (negative = paid). A is flat at 00/08/16 UTC so this should be 0."""
    rows = c.get("/fapi/v1/income", {"symbol": symbol, "incomeType": "FUNDING_FEE", "startTime": start_ms, "endTime": end_ms, "limit": 100}, signed=True)
    return sum(float(r.get("income", 0)) for r in rows or [])


def futures_setup(c, leverage, symbol=SYMBOL):
    """A's one-time setup: one-way mode, ISOLATED margin, leverage. Safe to call again (idempotent)."""
    events = []
    if c.get("/fapi/v1/positionSide/dual", signed=True).get("dualSidePosition"):
        c.post("/fapi/v1/positionSide/dual", {"dualSidePosition": "false"}); events.append("switched to one-way position mode")
    try:
        c.post("/fapi/v1/marginType", {"symbol": symbol, "marginType": "ISOLATED"}); events.append("margin type set to ISOLATED")
    except X.ExchangeError as e:
        if e.code != -4046: raise                     # -4046 = "No need to change margin type"
        events.append("margin type already ISOLATED")
    r = c.post("/fapi/v1/leverage", {"symbol": symbol, "leverage": int(leverage)})
    lev = int(float(r.get("leverage", leverage))); events.append(f"leverage {lev}x")
    return {"leverage": lev, "events": events}


# ---------------------------------------------------------------- orders
def _norm(c, o, **extra):
    filled = float(o.get("executedQty", 0) or 0)
    if c.futures:
        avg = float(o.get("avgPrice", 0) or 0)
    else:
        cq = float(o.get("cummulativeQuoteQty", 0) or 0); avg = cq / filled if filled else 0.0
    d = {"order_id": o.get("orderId"), "client_id": o.get("clientOrderId"), "status": o.get("status"), "side": o.get("side"),
         "type": o.get("type"), "price": float(o.get("price", 0) or 0), "qty": float(o.get("origQty", 0) or 0),
         "filled": filled, "avg_price": avg, "time_ms": o.get("updateTime") or o.get("transactTime") or o.get("time"), "note": ""}
    d.update(extra); return d


def _would_cross(e):
    return e.code == -5022 or (e.code == -2010 and "immediately" in str(e).lower())


def place_limit(c, side, price, qty, f, post_only=True, reduce_only=False, client_id=None, symbol=SYMBOL):
    """Limit order. Post-only orders that would cross return status EXPIRED with order_id None (not an exception)."""
    p = {"symbol": symbol, "side": side, "quantity": f.fmt_qty(qty), "price": f.fmt_price(price), "newClientOrderId": client_id}
    if c.futures:
        p.update(type="LIMIT", timeInForce="GTX" if post_only else "GTC")
        if reduce_only: p["reduceOnly"] = "true"
    else:
        p.update(type="LIMIT_MAKER" if post_only else "LIMIT", newOrderRespType="RESULT")
        if not post_only: p["timeInForce"] = "GTC"
    try:
        return _norm(c, c.post(f"{c.prefix}/{_v(c)}/order", p))
    except X.ExchangeError as e:
        if post_only and _would_cross(e):
            return {"order_id": None, "client_id": client_id, "status": "EXPIRED", "side": side, "type": p["type"], "price": float(price),
                    "qty": float(qty), "filled": 0.0, "avg_price": 0.0, "time_ms": None, "note": f"post-only rejected: {e}"}
        raise


def place_market(c, side, qty, f, reduce_only=False, client_id=None, symbol=SYMBOL, polls=10, sleep=time.sleep):
    p = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": f.fmt_qty(qty), "newClientOrderId": client_id}
    if c.futures and reduce_only: p["reduceOnly"] = "true"
    if not c.futures: p["newOrderRespType"] = "RESULT"
    o = _norm(c, c.post(f"{c.prefix}/{_v(c)}/order", p))
    for _ in range(polls):                                    # futures market orders can come back NEW for a moment
        if o["status"] in DONE_STATES: break
        sleep(0.5); o = get_order(c, o["order_id"], symbol)
    return o


def get_order(c, order_id, symbol=SYMBOL):
    return _norm(c, c.get(f"{c.prefix}/{_v(c)}/order", {"symbol": symbol, "orderId": order_id}, signed=True))


def cancel(c, order_id, symbol=SYMBOL):
    """Cancel; if Binance says 'unknown order' (already filled/cancelled) return its final state instead."""
    try:
        return _norm(c, c.delete(f"{c.prefix}/{_v(c)}/order", {"symbol": symbol, "orderId": order_id}))
    except X.ExchangeError as e:
        if e.code == -2011: return get_order(c, order_id, symbol)
        raise


def cancel_all(c, symbol=SYMBOL):
    try:
        r = c.delete("/fapi/v1/allOpenOrders" if c.futures else "/api/v3/openOrders", {"symbol": symbol})
    except X.ExchangeError as e:
        if e.code == -2011: return []                         # nothing open
        raise
    return r if isinstance(r, list) else [r]


def open_orders(c, symbol=SYMBOL):
    return [_norm(c, o) for o in c.get(f"{c.prefix}/{_v(c)}/openOrders", {"symbol": symbol}, signed=True)]


def fills_for(c, order_id, symbol=SYMBOL):
    """Trades (fills) for one order, with fees. Spot pays BUY fees in BTC and SELL fees in USDT; use fee_usdt()."""
    path = "/fapi/v1/userTrades" if c.futures else "/api/v3/myTrades"
    out = []
    for t in c.get(path, {"symbol": symbol, "orderId": order_id}, signed=True) or []:
        if int(t.get("orderId", order_id)) != int(order_id): continue
        maker = t["maker"] if "maker" in t else t.get("isMaker")
        out.append({"trade_id": t.get("id"), "order_id": t.get("orderId"), "price": float(t["price"]), "qty": float(t["qty"]),
                    "fee": float(t.get("commission", 0)), "fee_asset": t.get("commissionAsset", ""), "maker": bool(maker),
                    "realized_pnl": float(t.get("realizedPnl", 0) or 0), "time_ms": t.get("time")})
    return out


_fee_prices = {}


def fee_usdt(tr, client=None):
    """A fill's fee in USDT. BTC fees convert at the fill price; BNB (or any other asset) at its USDT ticker, fetched once
    per run from `client` (or the real public spot host). Never raises after a trade: unknown -> 0 with a note."""
    asset = tr["fee_asset"]
    if asset in ("USDT", "USDC", "BUSD", "") or tr["fee"] == 0: return tr["fee"]
    if asset == "BTC": return tr["fee"] * tr["price"]
    if asset not in _fee_prices:
        for c in (client, real_client(False)):
            if c is None: continue
            try:
                _fee_prices[asset] = last_price(c, f"{asset}USDT"); break
            except X.ExchangeError:
                continue
    px = _fee_prices.get(asset)
    if px is None:
        print(f"WARNING: fee paid in {asset} and no {asset}USDT price available: fee logged as 0 USDT"); return 0.0
    return tr["fee"] * px


def avg_price(fills):
    q = sum(t["qty"] for t in fills)
    return sum(t["qty"] * t["price"] for t in fills) / q if q else 0.0


# ---------------------------------------------------------------- loops
def work_order(c, side, qty, deadline, f, post_only=True, reduce_only=False, poll=2.0, on_event=None,
               clock=time.time, sleep=time.sleep, tag="", symbol=SYMBOL):
    """Keep ONE limit order at the touch (BUY: best bid, SELL: best ask) until it is filled or `deadline` (epoch s).
    Re-posts the remainder when the touch moves against us (bid up / ask down). Partial fills are kept.
    Never crosses the spread: a post-only order that would cross is simply re-read from the book on the next poll.
    Returns {side, target_qty, filled, avg_price, orders, fills, events, books, complete}. Raises ExchangeError on
    anything unexpected (rejects, outages): the caller must log an alert."""
    res = {"side": side, "target_qty": float(qty), "filled": 0.0, "avg_price": 0.0, "orders": [], "fills": [], "events": [], "books": []}
    done, cur, n = 0.0, None, 0

    def ev(msg, **kw):
        rec = {"ts": iso(clock()), "msg": msg, **kw}; res["events"].append(rec)
        if on_event: on_event(rec)

    def settle(o):
        nonlocal done
        res["orders"].append(o)
        if o["order_id"] is not None and o["filled"] > 0:
            res["fills"] += fills_for(c, o["order_id"], symbol)
        done += o["filled"]

    while clock() < deadline:
        b = book(c, symbol); res["books"].append(b)
        touch = b["bid"] if side == "BUY" else b["ask"]
        if cur is None:
            remaining = f.qty(qty - done)
            why = f.too_small(remaining, touch)
            if why: ev("nothing left to post", reason=why); break
            n += 1
            o = place_limit(c, side, touch, remaining, f, post_only, reduce_only, client_id=f"{tag}{int(clock() * 1000) % 10 ** 9}-{n}"[:36], symbol=symbol)
            if o["order_id"] is None or o["status"] == "EXPIRED":
                ev("post-only order would have crossed; re-reading the book", price=touch, note=o.get("note", "")); sleep(poll); continue
            cur = o; ev("placed", order_id=o["order_id"], price=touch, qty=remaining, bid=b["bid"], ask=b["ask"])
            if o["status"] == "FILLED":                       # can't happen for post-only, but be safe
                settle(o); cur = None; ev("filled", order_id=o["order_id"], avg_price=o["avg_price"]); break
        else:
            o = get_order(c, cur["order_id"], symbol); cur = o
            if o["status"] == "FILLED":
                settle(o); cur = None; ev("filled", order_id=o["order_id"], avg_price=o["avg_price"], qty=o["filled"]); break
            if o["status"] not in OPEN_STATES:
                settle(o); cur = None; ev(f"order ended with status {o['status']}", order_id=o["order_id"], filled=o["filled"]); continue
            moved = touch > o["price"] if side == "BUY" else touch < o["price"]
            if moved:
                o2 = cancel(c, o["order_id"], symbol); settle(o2); cur = None
                ev("touch moved: cancelled, re-posting", order_id=o["order_id"], old_price=o["price"], new_touch=touch, filled_so_far=o2["filled"]); continue
        sleep(poll)
    if cur is not None:
        o2 = cancel(c, cur["order_id"], symbol); settle(o2)
        ev("deadline: cancelled the remainder", order_id=cur["order_id"], filled=o2["filled"], unfilled=f.qty(qty - done))
    res["filled"] = done
    res["avg_price"] = avg_price(res["fills"]) if res["fills"] else (sum(o["filled"] * o["avg_price"] for o in res["orders"]) / done if done else 0.0)
    left = f.qty(qty - done)
    res["complete"] = left < float(f.step) or f.too_small(left, res["books"][-1]["mid"] if res["books"] else 1) is not None
    return res


def market_rest(c, side, qty, f, reduce_only=False, tag="", symbol=SYMBOL, sleep=time.sleep):
    """Market order for `qty` (rounded down). Returns {order, fills, avg_price} or None if too small to send."""
    q = f.qty(qty)
    if q < float(f.min_qty) or q <= 0: return None
    o = place_market(c, side, q, f, reduce_only=reduce_only, client_id=f"{tag}{int(time.time() * 1000) % 10 ** 9}-m"[:36], symbol=symbol, sleep=sleep)
    fills = fills_for(c, o["order_id"], symbol) if o["filled"] > 0 else []
    return {"order": o, "fills": fills, "avg_price": avg_price(fills) if fills else o["avg_price"]}
