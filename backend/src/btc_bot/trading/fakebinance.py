"""
A small fake Binance (spot + USD-M futures) for offline tests and dry runs. No network beyond 127.0.0.1.

Sim(futures=...) holds one venue's state: order book (best bid/ask), open orders, trades, balances or position.
serve(spot_sim, fut_sim) starts a local HTTP server that answers the endpoints exchange.py / orders.py use, with
Binance's response shapes and error codes, so the real client code is exercised end to end:
  post-only orders that would cross:  futures -> status EXPIRED, spot -> error -2010 "would immediately match"
  cancel of a finished order:         -2011 "Unknown order sent."
  marginType already set:             -4046
  reduceOnly beyond the position:     clipped to the position (as Binance does)
Fills are driven by the test: sim.script is a list of steps consumed one per bookTicker call, e.g.
  {"bid": 65000.0, "ask": 65000.1}                  move the book
  {"fill": 0.02}                                     fill resting orders at the touch, up to 0.02 BTC (maker fee)
  {"error": (-1001, "internal error")}               next order request fails with this code
Market orders fill immediately at the touch with the taker fee. Spot fees: BUY in BTC, SELL in USDT (as Binance).
"""
import json, socket, threading, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlparse


class Sim:
    def __init__(self, futures, bid=65000.0, ask=65000.1, usdt=5000.0, btc=0.0, maker=None, taker=None):
        self.futures = futures
        self.bid, self.ask = float(bid), float(ask)
        self.maker = maker if maker is not None else (0.0002 if futures else 0.001)
        self.taker = taker if taker is not None else (0.0004 if futures else 0.001)
        self.usdt, self.btc = float(usdt), float(btc)          # spot balances / futures wallet (btc unused for futures)
        self.locked_usdt = self.locked_btc = 0.0
        self.pos, self.entry, self.realized = 0.0, 0.0, 0.0     # futures position
        self.leverage, self.margin_type, self.dual = 20, "CROSSED", False
        self.orders, self.trades, self.script, self.log = {}, [], [], []
        self.next_order, self.next_trade = 1000, 5000
        self.pending_error = None
        self.bnb_fees = False       # spot: pay fees in BNB (0.075% discount) like a real account with BNB
        self.auto_fill = False      # dry runs: every resting order at the touch fills on the next book read
        self.tick, self.step = (0.10, 0.001) if futures else (0.01, 0.00001)
        self.min_notional = 100.0 if futures else 5.0
        self.calls = []

    # ---- state helpers
    STATE_KEYS = ("bid", "ask", "usdt", "btc", "locked_usdt", "locked_btc", "pos", "entry", "realized", "leverage", "margin_type", "dual",
                  "orders", "trades", "next_order", "next_trade")

    def save(self, path):
        """Persist balances/orders/trades so a dry run keeps its state between harness commands."""
        import json as _j
        d = {k: getattr(self, k) for k in self.STATE_KEYS}; d["orders"] = {str(k): v for k, v in self.orders.items()}
        Path(path).parent.mkdir(parents=True, exist_ok=True); Path(path).write_text(_j.dumps(d))

    def load(self, path):
        import json as _j
        if not Path(path).exists(): return False
        d = _j.loads(Path(path).read_text())
        for k in self.STATE_KEYS:
            if k in d: setattr(self, k, d[k])
        self.orders = {int(k): v for k, v in self.orders.items()}
        return True

    @property
    def mid(self): return (self.bid + self.ask) / 2

    def step_script(self):
        if not self.script:
            if self.auto_fill: self.fill_resting(1e9)
            return
        s = self.script.pop(0)
        if "bid" in s: self.bid = float(s["bid"])
        if "ask" in s: self.ask = float(s["ask"])
        if "error" in s: self.pending_error = tuple(s["error"])
        if "fill" in s: self.fill_resting(float(s["fill"]))

    def fill_resting(self, qty):
        """Fill open orders sitting at (or better than) the touch, up to qty BTC in total, as a maker."""
        for o in list(self.orders.values()):
            if o["status"] not in ("NEW", "PARTIALLY_FILLED") or qty <= 0: continue
            px = float(o["price"])
            at_touch = (o["side"] == "BUY" and px >= self.bid) or (o["side"] == "SELL" and px <= self.ask)
            if not at_touch: continue
            rem = float(o["origQty"]) - float(o["executedQty"])
            q = min(rem, qty); qty -= q
            self._exec(o, q, px, maker=True)

    def _exec(self, o, q, px, maker):
        fee_rate = self.maker if maker else self.taker
        tr = {"id": self.next_trade, "orderId": o["orderId"], "symbol": "BTCUSDT", "side": o["side"], "price": f"{px:.8f}", "qty": f"{q:.8f}",
              "quoteQty": f"{q * px:.8f}", "time": self.now_ms(), "maker": maker, "isMaker": maker, "isBuyer": o["side"] == "BUY", "realizedPnl": "0"}
        self.next_trade += 1
        if self.futures:
            fee = q * px * fee_rate; tr.update(commission=f"{fee:.8f}", commissionAsset="USDT")
            if o["side"] == "BUY":
                self.entry = (self.entry * self.pos + px * q) / (self.pos + q) if self.pos + q else 0.0; self.pos += q
            else:
                pnl = (px - self.entry) * min(q, self.pos); self.pos -= q; tr["realizedPnl"] = f"{pnl:.8f}"; self.usdt += pnl
                if self.pos <= 1e-12: self.pos, self.entry = 0.0, 0.0
            self.usdt -= fee
        else:
            if self.bnb_fees:
                fee = q * px * fee_rate * 0.75 / 600.0; tr.update(commission=f"{fee:.8f}", commissionAsset="BNB")   # BNB at 600 USDT
                if o["side"] == "BUY": self.usdt -= q * px; self.btc += q
                else: self.btc -= q; self.usdt += q * px
                if o["type"] != "MARKET":
                    if o["side"] == "BUY": self.locked_usdt -= q * float(o["price"])
                    else: self.locked_btc -= q
            elif o["side"] == "BUY":
                fee = q * fee_rate; tr.update(commission=f"{fee:.8f}", commissionAsset="BTC")
                self.usdt -= q * px; self.btc += q - fee
                if o["type"] != "MARKET": self.locked_usdt -= q * float(o["price"])
            else:
                fee = q * px * fee_rate; tr.update(commission=f"{fee:.8f}", commissionAsset="USDT")
                self.btc -= q; self.usdt += q * px - fee
                if o["type"] != "MARKET": self.locked_btc -= q
        self.trades.append(tr)
        ex = float(o["executedQty"]) + q
        o["executedQty"] = f"{ex:.8f}"
        o["cummulativeQuoteQty"] = f"{float(o['cummulativeQuoteQty']) + q * px:.8f}"
        o["avgPrice"] = f"{float(o['cummulativeQuoteQty']) / ex:.8f}"
        o["status"] = "FILLED" if ex >= float(o["origQty"]) - 1e-12 else "PARTIALLY_FILLED"
        o["updateTime"] = self.now_ms()

    def now_ms(self): return int(time.time() * 1000)

    # ---- order handling
    def _err(self, code, msg): return 400, {"code": code, "msg": msg}

    def place(self, p):
        if self.pending_error:
            code, msg = self.pending_error; self.pending_error = None; return self._err(code, msg)
        side, typ = p["side"], p["type"]
        qty = float(p["quantity"]); price = float(p.get("price", 0) or 0)
        if qty <= 0: return self._err(-1013, "Invalid quantity.")
        post_only = (self.futures and p.get("timeInForce") == "GTX") or (not self.futures and typ == "LIMIT_MAKER")
        reduce_only = str(p.get("reduceOnly", "false")).lower() == "true"
        if self.futures and reduce_only:
            if self.pos <= 0 or side != "SELL": return self._err(-2022, "ReduceOnly Order is rejected")
            qty = min(qty, self.pos)
        if typ != "MARKET" and price <= 0: return self._err(-1013, "Invalid price.")
        if not self.futures and typ != "MARKET":
            if side == "BUY" and qty * price > self.usdt - self.locked_usdt + 1e-9: return self._err(-2010, "Account has insufficient balance for requested action.")
            if side == "SELL" and qty > self.btc - self.locked_btc + 1e-9: return self._err(-2010, "Account has insufficient balance for requested action.")
        if not self.futures and typ == "MARKET":
            if side == "BUY" and qty * self.ask > self.usdt - self.locked_usdt + 1e-9: return self._err(-2010, "Account has insufficient balance for requested action.")
            if side == "SELL" and qty > self.btc - self.locked_btc + 1e-9: return self._err(-2010, "Account has insufficient balance for requested action.")
        if typ != "MARKET" and qty * price < self.min_notional: return self._err(-4164 if self.futures else -1013, "Order's notional must be no smaller than min notional")
        o = {"orderId": self.next_order, "clientOrderId": p.get("newClientOrderId") or f"auto{self.next_order}", "symbol": "BTCUSDT",
             "side": side, "type": typ, "timeInForce": p.get("timeInForce", "GTC"), "price": f"{price:.8f}", "origQty": f"{qty:.8f}",
             "executedQty": "0", "cummulativeQuoteQty": "0", "avgPrice": "0", "status": "NEW", "reduceOnly": reduce_only,
             "time": self.now_ms(), "updateTime": self.now_ms(), "transactTime": self.now_ms()}
        self.next_order += 1
        crosses = (side == "BUY" and price >= self.ask) or (side == "SELL" and price <= self.bid)
        if typ == "MARKET":
            self.orders[o["orderId"]] = o
            self._exec(o, qty, self.ask if side == "BUY" else self.bid, maker=False)
            return 200, o
        if post_only and crosses:
            if self.futures:
                o["status"] = "EXPIRED"; self.orders[o["orderId"]] = o; return 200, o
            return self._err(-2010, "Order would immediately match and take.")
        if crosses:                                     # plain limit that crosses: fill as taker
            self.orders[o["orderId"]] = o; self._exec(o, qty, self.ask if side == "BUY" else self.bid, maker=False); return 200, o
        self.orders[o["orderId"]] = o
        if not self.futures:
            if side == "BUY": self.locked_usdt += qty * price
            else: self.locked_btc += qty
        return 200, o

    def cancel(self, oid):
        o = self.orders.get(oid)
        if not o or o["status"] not in ("NEW", "PARTIALLY_FILLED"): return self._err(-2011, "Unknown order sent.")
        o["status"] = "CANCELED"; o["updateTime"] = self.now_ms()
        if not self.futures:
            rem = float(o["origQty"]) - float(o["executedQty"])
            if o["side"] == "BUY": self.locked_usdt -= rem * float(o["price"])
            else: self.locked_btc -= rem
        return 200, o

    def cancel_all(self):
        out = [self.cancel(k)[1] for k, o in list(self.orders.items()) if o["status"] in ("NEW", "PARTIALLY_FILLED")]
        return (200, out) if out or self.futures else self._err(-2011, "Unknown order sent.")

    # ---- account shapes
    def account(self):
        if self.futures:
            unreal = (self.mid - self.entry) * self.pos
            margin = self.pos * self.entry / self.leverage
            return {"totalWalletBalance": f"{self.usdt:.8f}", "totalUnrealizedProfit": f"{unreal:.8f}",
                    "totalMarginBalance": f"{self.usdt + unreal:.8f}", "availableBalance": f"{self.usdt - margin:.8f}"}
        return {"canTrade": True, "canWithdraw": True, "accountType": "SPOT", "balances": [
            {"asset": "USDT", "free": f"{self.usdt - self.locked_usdt:.8f}", "locked": f"{self.locked_usdt:.8f}"},
            {"asset": "BTC", "free": f"{self.btc - self.locked_btc:.8f}", "locked": f"{self.locked_btc:.8f}"}]}

    def position_risk(self):
        return [{"symbol": "BTCUSDT", "positionAmt": f"{self.pos:.8f}", "entryPrice": f"{self.entry:.8f}", "markPrice": f"{self.mid:.8f}",
                 "unRealizedProfit": f"{(self.mid - self.entry) * self.pos:.8f}", "leverage": str(self.leverage), "marginType": self.margin_type.lower()}]

    def exchange_info(self):
        return {"symbols": [{"symbol": "BTCUSDT", "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": f"{self.tick:.8f}".rstrip("0") if self.tick < 1 else str(self.tick)},
            {"filterType": "LOT_SIZE", "stepSize": f"{self.step:.8f}", "minQty": f"{self.step:.8f}"},
            {"filterType": "MIN_NOTIONAL" if self.futures else "NOTIONAL", "notional": str(self.min_notional), "minNotional": str(self.min_notional)}]}]}

    # ---- router
    def handle(self, method, path, p):
        self.calls.append((method, path))
        e = lambda *a: self._err(*a)
        if path.endswith("/time"): return 200, {"serverTime": self.now_ms()}
        if path.endswith("/exchangeInfo"): return 200, self.exchange_info()
        if path.endswith("/ticker/bookTicker"):
            self.step_script(); return 200, {"symbol": "BTCUSDT", "bidPrice": f"{self.bid:.8f}", "askPrice": f"{self.ask:.8f}", "bidQty": "1", "askQty": "1"}
        if path.endswith("/ticker/price"):
            if p.get("symbol") == "BNBUSDT": return 200, {"symbol": "BNBUSDT", "price": "600.00000000"}
            return 200, {"symbol": "BTCUSDT", "price": f"{self.mid:.8f}"}
        if path.endswith("/premiumIndex"): return 200, {"symbol": "BTCUSDT", "markPrice": f"{self.mid:.8f}", "lastFundingRate": "0.0001", "nextFundingTime": 0}
        if path.endswith("/account") or path.endswith("/balance"):
            if path.endswith("/balance"): return 200, [{"asset": "USDT", "balance": f"{self.usdt:.8f}", "availableBalance": f"{self.usdt:.8f}"}]
            return 200, self.account()
        if path.endswith("/positionRisk"): return 200, self.position_risk()
        if path.endswith("/positionSide/dual"):
            if method == "POST": self.dual = str(p.get("dualSidePosition")).lower() == "true"; return 200, {"code": 200, "msg": "success"}
            return 200, {"dualSidePosition": self.dual}
        if path.endswith("/marginType"):
            if p.get("marginType") == self.margin_type: return e(-4046, "No need to change margin type.")
            if self.pos: return e(-4048, "Margin type cannot be changed if there exists position.")
            self.margin_type = p["marginType"]; return 200, {"code": 200, "msg": "success"}
        if path.endswith("/leverage"):
            self.leverage = int(p["leverage"]); return 200, {"leverage": self.leverage, "maxNotionalValue": "1000000", "symbol": "BTCUSDT"}
        if path.endswith("/income"): return 200, []
        if path.endswith("/userTrades") or path.endswith("/myTrades"):
            oid = p.get("orderId"); return 200, [t for t in self.trades if oid is None or t["orderId"] == int(oid)]
        if path.endswith("/openOrders"):
            if method == "DELETE": return self.cancel_all()
            return 200, [o for o in self.orders.values() if o["status"] in ("NEW", "PARTIALLY_FILLED")]
        if path.endswith("/allOpenOrders"): return self.cancel_all()
        if path.endswith("/order"):
            if method == "POST": return self.place(p)
            oid = int(p.get("orderId", 0))
            if method == "DELETE": return self.cancel(oid)
            o = self.orders.get(oid)
            return (200, o) if o else e(-2013, "Order does not exist.")
        return 404, {"code": -1, "msg": f"no fake for {method} {path}"}


class _Handler(BaseHTTPRequestHandler):
    sims = {}
    def log_message(self, *a): pass
    def _go(self):
        u = urlparse(self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode() if self.command in ("POST", "PUT") else ""
        p = dict(parse_qsl(u.query)); p.update(dict(parse_qsl(body)))
        sim = self.sims["fapi" if u.path.startswith("/fapi") else "api"]
        if sim is None: code, out = 404, {"code": -1, "msg": "venue not simulated"}
        else: code, out = sim.handle(self.command, u.path, p)
        b = json.dumps(out).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
    do_GET = do_POST = do_DELETE = do_PUT = _go


def serve(spot=None, futures=None):
    """Start a local server for the given sims. Returns (server, base_url). Call server.shutdown() when done."""
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    cls = type("H", (_Handler,), {"sims": {"api": spot, "fapi": futures}})
    srv = ThreadingHTTPServer(("127.0.0.1", port), cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{port}"
