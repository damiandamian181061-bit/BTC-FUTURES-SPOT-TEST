"""
Telegram notifications for the scheduled bot (added 17 Nov 2026, once the bot ran on the Droplet and nobody watched the
laptop any more). Read-only on the ledgers: it never trades and never writes to data/paper/.

  btc-bot notify setup        once, interactive, on the laptop (WSL): asks for the bot token (hidden), finds your chat
                              with the bot, stores both in the secrets file, sends a test message.
                              Then copy the file to the Droplet: bash deploy/digitalocean/do.sh bot-keys
  btc-bot notify test         send a test message with the stored settings
  btc-bot notify after-run --command C --rc N --since TS [--print-only]
                              called by deploy/digitalocean/bot-run.sh after every scheduled run (TS = run start, UTC);
                              --print-only shows the messages without sending them

What is sent (Damian's choice, 17 Nov 2026: "problems + trades + daily"):
  problem   at once: every ERROR or WARN alert the run wrote; a run that exited non-zero without an alert gets the
            last lines of its log instead (crash, container or Docker trouble)
  trade     at once: B switched (b-check), A entered or went unfilled (a-enter), A closed (a-exit)
  daily     after the 23:10 UTC dashboard run: today's runs, B, A, equity, alerts, kill switches. It is also the
            heartbeat: no daily message by ~23:15 UTC means the server or its schedule is down.

Settings live in the same secrets file as the Binance keys (never in .env, never in git; environment variables of the
same names win, as for the keys):
  TELEGRAM_BOT_TOKEN=<from @BotFather>
  TELEGRAM_CHAT_ID=<your chat with the bot; `notify setup` finds it>
Without a token nothing is sent (bot-run.sh skips the step). The token is only ever put in the request URL: it never
appears in output, logs or error messages.
"""
import argparse, getpass, json, os, re, socket, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.dont_write_bytecode = True
from ..config import SECRETS_FILE
from ..trading import ledger as L
from ..trading.exchange import _read_keyfile

API = "https://api.telegram.org"
KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
MAX_LEN = 4000                      # Telegram's limit is 4096 characters per message
# the five scheduled runs, UTC; same as reporting/dashboard.py RUN_TIMES (a test keeps them equal). Not imported from
# there so that a broken dashboard or data file can never stop the problem messages.
SCHEDULED = {"b-check": (0, 1), "a-precheck": (20, 55), "a-enter": (21, 0), "a-exit": (22, 55), "dashboard": (23, 10)}
GRACE_MIN = 20                      # a run counts as missing this many minutes after its time (as on the dashboard)


class NotifyError(Exception):
    """Telegram could not be reached or refused the request. The message never contains the token."""


# ---------------------------------------------------------------- settings and sending
def load_settings(path=None):
    """{TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID} from the secrets file, overlaid by non-empty environment variables."""
    p = Path(path or SECRETS_FILE); out = {}
    if p.is_file():
        try:
            out = {k: v for k, v in _read_keyfile(p).items() if k in KEYS and v}
        except OSError:
            pass
    if path is None:
        out.update({k: os.environ[k].strip() for k in KEYS if os.environ.get(k, "").strip()})
    return out


def _api(token, method, params=None, timeout=15):
    """One Bot API call; returns its `result`. Errors are re-raised as NotifyError without the URL (it holds the token)."""
    req = urllib.request.Request(f"{API}/bot{token}/{method}", data=urllib.parse.urlencode(params or {}).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            desc = json.loads(e.read().decode("utf-8")).get("description", "")
        except Exception:  # noqa: BLE001
            desc = ""
        finally:
            e.close()
        raise NotifyError(f"Telegram {method}: HTTP {e.code} {desc}".strip()) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError, ValueError) as e:
        raise NotifyError(f"Telegram {method}: {getattr(e, 'reason', None) or type(e).__name__}") from None
    if not body.get("ok"):
        raise NotifyError(f"Telegram {method}: {body.get('description', 'not ok')}")
    return body.get("result")


def send(text, settings=None, api=None, tries=2, pause=3.0):
    """Send one plain-text message (cut to MAX_LEN). Raises NotifyError if not configured or every try failed."""
    s = load_settings() if settings is None else settings
    if not s.get("TELEGRAM_BOT_TOKEN") or not s.get("TELEGRAM_CHAT_ID"):
        raise NotifyError("not configured: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing (run: btc-bot notify setup)")
    api = api or _api
    if len(text) > MAX_LEN: text = text[:MAX_LEN - 12] + "\n... (cut)"
    err = None
    for i in range(max(1, tries)):
        try:
            api(s["TELEGRAM_BOT_TOKEN"], "sendMessage", {"chat_id": s["TELEGRAM_CHAT_ID"], "text": text, "disable_web_page_preview": "true"})
            return True
        except NotifyError as e:
            err = e
            if i + 1 < tries: time.sleep(pause)
    raise err


# ---------------------------------------------------------------- message text
def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v                                      # NaN -> None


def _n(x, d=0):
    v = _f(x); return "n/a" if v is None else f"{v:,.{d}f}"


def _sgn(x, d=2, unit=""):
    v = _f(x); return "n/a" if v is None else f"{v:+,.{d}f}{unit}"


def _vs(a, b):
    a, b = _f(a), _f(b); return "?" if a is None or b is None else (">" if a > b else "<")


def problem_message(command, rc, alerts, log_tail=None):
    """None when the run went as intended: exit 0 and no ERROR/WARN alert. `alerts` = the rows this run wrote."""
    bad = [a for a in alerts if a.get("level") in ("ERROR", "WARN")]
    if not bad and rc == 0: return None
    serious = rc != 0 or any(a.get("level") == "ERROR" for a in bad)
    lines = [f"\U0001F534 BTC bot problem: {command} (exit {rc})" if serious else f"\U0001F7E0 BTC bot warning: {command} (exit {rc})"]
    if len(bad) > 8: lines.append(f"{len(bad)} alerts, the last 8:")
    for a in bad[-8:]:
        lines.append(f"{a.get('level')} {a.get('command', '')} {a.get('ts_utc', '')[11:16]} UTC: {a.get('message', '')}")
    if not bad:
        lines.append("The run logged no alert (crash, container or Docker trouble?).")
        if log_tail: lines += ["Last log lines:", *log_tail]
    lines.append(f"Log on the server: paper/logs/{command}.log (website: Operations)")
    return "\n".join(lines)


def trade_message(command, run, b_row=None, a_row=None, equity_row=None):
    """A message when this run traded, else None. `run` = this run's runs.csv row (its note says what happened)."""
    if not run: return None
    note = run.get("note", "")
    eq = f"Equity {_n(equity_row.get('equity_usdt'), 2)} USDT" if equity_row else ""
    if command == "b-check" and b_row and b_row.get("action") in ("BUY", "SELL") \
            and (note.startswith("switched") or b_row.get("status") == "SWITCH_INCOMPLETE"):
        head = "\U0001F7E2 B switched" if b_row.get("status") == "SWITCHED" else "\U0001F534 B switch INCOMPLETE"
        return "\n".join([
            f"{head}: {b_row.get('held_before')} -> {b_row.get('target')} (close {_n(b_row.get('close_prev'))} "
            f"{_vs(b_row.get('close_prev'), b_row.get('sma50'))} SMA50 {_n(b_row.get('sma50'))})",
            f"{b_row.get('action')} {_n(b_row.get('qty'), 5)} BTC @ {_n(b_row.get('avg_price'), 2)} | fee {_n(b_row.get('fee_usdt'), 2)} USDT | "
            f"slippage vs real mid {_sgn(b_row.get('slip_real_bp'), 1, ' bp')}",
            f"Equity {_n(b_row.get('equity_usdt'), 2)} USDT"])
    if command == "a-enter" and a_row and note.startswith(("ENTERED", "UNFILLED")):
        if a_row.get("status") == "UNFILLED":
            return ("⚪ A: entry not filled by 21:05 UTC, no trade tonight (rule 3.2: never a market buy). "
                    f"Counts against the 80% fill rate. 20:55 price {_n(a_row.get('price_2055'))} > SMA200 {_n(a_row.get('sma200'))}")
        if a_row.get("status") == "ENTERED":
            fr = _f(a_row.get("fill_rate"))
            return "\n".join([
                f"\U0001F7E2 A entered: BUY {_n(a_row.get('entry_filled'), 5)} of {_n(a_row.get('target_qty'), 5)} BTC @ "
                f"{_n(a_row.get('entry_avg'), 2)} (fill {'n/a' if fr is None else f'{fr:.0%}'})",
                f"20:55 price {_n(a_row.get('price_2055'))} > SMA200 {_n(a_row.get('sma200'))} | slippage vs real mid "
                f"{_sgn(a_row.get('entry_slip_real_bp'), 1, ' bp')} | fee {_n(a_row.get('fees_usdt'), 2)} USDT",
                "Exit 22:55-23:00 UTC"])
    if command == "a-exit" and a_row and a_row.get("status") == "CLOSED" and note.startswith("closed"):
        return "\n".join([
            f"\U0001F7E2 A closed: SELL @ {_n(a_row.get('exit_avg'), 2)} ({a_row.get('exit_type')}) | P&L {_sgn(a_row.get('pnl_usdt'))} USDT "
            f"({_sgn(a_row.get('pnl_bp'), 1, ' bp')}) after fees {_n(a_row.get('fees_usdt'), 2)} USDT, funding {_sgn(a_row.get('funding_usdt'))}",
            f"Entry {_n(a_row.get('entry_avg'), 2)} | exit slippage vs real mid {_sgn(a_row.get('exit_slip_real_bp'), 1, ' bp')}",
            eq]).rstrip()
    return None


def _a_line(a):
    """(text, problem or None) for today's A row."""
    st = a.get("status") if a else None
    px, sma = a.get("price_2055") if a else None, a.get("sma200") if a else None
    if st is None: return "A: no 20:55 pre-check logged today", "A: no pre-check today"
    if st == "SKIPPED_FILTER": return f"A: off tonight (20:55 price {_n(px)} < SMA200 {_n(sma)})", None
    if st == "UNFILLED": return f"A: allowed (price {_n(px)} > SMA200 {_n(sma)}), entry not filled: no trade", None
    if st == "CLOSED":
        return (f"A: traded | P&L {_sgn(a.get('pnl_usdt'))} USDT ({_sgn(a.get('pnl_bp'), 1, ' bp')}) | exit {a.get('exit_type')} | "
                f"fill {_n((_f(a.get('fill_rate')) or 0) * 100)}%"), None
    if st == "ALLOWED": return "A: allowed at 20:55 but no entry logged", "A: allowed but no a-enter result"
    if st == "ENTERED": return "A: entered but no exit logged", "A: entered, no a-exit result: check the position"
    return f"A: {st}", f"A: {st}"                                     # STILL_OPEN, MISSED_MACHINE_OFF, ERROR


def _b_line(b):
    st = b.get("status") if b else None
    if st is None: return "B: no b-check logged today", "B: no b-check today"
    sig = f"close {_n(b.get('close_prev'))} {_vs(b.get('close_prev'), b.get('sma50'))} SMA50 {_n(b.get('sma50'))}"
    if st == "NO_CHANGE": return f"B: {b.get('target')}, no change ({sig})", None
    if st == "SWITCHED": return f"B: switched to {b.get('target')} ({b.get('action')} @ {_n(b.get('avg_price'), 2)}; {sig})", None
    return f"B: {st} ({sig})", f"B: {st}"                            # NO_TRADE, SWITCH_INCOMPLETE


def daily_message(now, runs, alerts, b_row=None, a_row=None, eq_b=None, eq_a=None, dash=None):
    """The 23:10 UTC summary of today (UTC). `alerts` = all alert rows; `dash` = dashboard.json (or None)."""
    day = now.strftime("%Y-%m-%d"); problems = []
    cells = []
    for cmd, (h, m) in SCHEDULED.items():
        hit = [r for r in runs if r.get("command") == cmd and r.get("day") == day]
        if hit: st = hit[-1].get("status", "?")
        else: st = "MISSING" if now >= now.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(minutes=GRACE_MIN) else "pending"
        if st not in ("OK", "pending"): problems.append(f"{cmd} {st}")
        cells.append(f"{cmd} {st}")
    b_txt, b_prob = _b_line(b_row); a_txt, a_prob = _a_line(a_row)
    problems += [p for p in (b_prob, a_prob) if p]
    eb, ea = _f(eq_b.get("equity_usdt")) if eq_b else None, _f(eq_a.get("equity_usdt")) if eq_a else None
    equity = f"Equity: B {_n(eb, 2)} + A {_n(ea, 2)} = {_n((eb or 0) + (ea or 0), 2)} USDT" if eb is not None or ea is not None else "Equity: n/a"
    today_alerts = [a for a in alerts if a.get("ts_utc", "").startswith(day)]
    levels = {}
    for a in today_alerts: levels[a.get("level")] = levels.get(a.get("level"), 0) + 1
    worst = [a for a in today_alerts if a.get("level") in ("ERROR", "WARN")]
    al = "Alerts today: none" if not today_alerts else "Alerts today: " + ", ".join(f"{n} {k}" for k, n in sorted(levels.items()))
    al_lines = [f"  {a.get('level')} {a.get('command')}: {a.get('message', '')[:120]}" for a in worst[-3:]]
    if worst: problems.append(f"{len(worst)} ERROR/WARN alert(s)")
    # how far the price is from the levels that switch each strategy on (when they are off)
    far = []
    px, sma200 = _f(a_row.get("price_2055")) if a_row else None, _f(a_row.get("sma200")) if a_row else None
    if px and sma200 and px < sma200: far.append(f"A needs +{(sma200 / px - 1):.1%} (SMA200 {_n(sma200)})")
    cl, sma50 = _f(b_row.get("close_prev")) if b_row else None, _f(b_row.get("sma50")) if b_row else None
    if cl and sma50 and cl < sma50 and b_row.get("target") == "CASH": far.append(f"B needs +{(sma50 / cl - 1):.1%} (SMA50 {_n(sma50)})")
    kill, extra = [], []
    if dash is None:
        problems.append("dashboard.json missing")
    else:
        try:
            gen = datetime.fromisoformat(str(dash.get("generated_utc")).replace("Z", "+00:00"))
            fresh = gen.tzinfo is not None and timedelta(0) <= now - gen <= timedelta(hours=2)
        except ValueError:
            fresh = False
        if not fresh: problems.append(f"dashboard.json not refreshed (generated {dash.get('generated_utc')})")
        kill = [k for k in dash.get("kill", []) if k.get("status") in ("warn", "bad")]
        if any(k.get("status") == "bad" for k in kill): problems.append("kill switch hit")
        missed = (dash.get("ops") or {}).get("missed")
        if missed: extra.append(f"Missed scheduled runs in the 14-day grid: {missed}")
    pd_ = f" (paper day {dash['paper_days']})" if dash and dash.get("paper_days") else ""
    head = (f"⚠️ BTC bot daily {now:%a %d %b}{pd_}: {len(problems)} problem(s)" if problems
            else f"\U0001F4CB BTC bot daily {now:%a %d %b}{pd_}: all OK")
    lines = [head]
    if problems: lines.append("Problems: " + "; ".join(problems))
    lines += ["Runs: " + " | ".join(cells), b_txt, a_txt, equity]
    if far: lines.append("To trade: " + " | ".join(far))
    lines += [al, *al_lines]
    lines.append("Kill switches: " + ("none hit" if not kill else "; ".join(f"[{k.get('status')}] {k.get('trigger')}: {k.get('reading')}" for k in kill)))
    lines += extra
    return "\n".join(lines)


# ---------------------------------------------------------------- after a scheduled run (bot-run.sh)
def _log_tail(command, n=8):
    p = L.paper_dir() / "logs" / f"{command}.log"
    if not p.is_file(): return []
    lines = [ln.rstrip()[:200] for ln in p.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
             if ln.strip() and not ln.strip().startswith("Container ")]
    return lines[-n:]


def _dashboard_json():
    p = L.paper_dir() / "dashboard.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build_after_run(command, rc, since, now=None):
    """The messages for one finished run, in sending order (problem, trade, daily). Reads the ledgers only."""
    now = now or datetime.now(timezone.utc)
    alerts = L.rows("alerts")
    mine = [a for a in alerts if a.get("ts_utc", "") >= since]
    run = next((r for r in reversed(L.rows("runs")) if r.get("command") == command and r.get("ts_utc", "") >= since), None)
    day = (run or {}).get("day") or now.strftime("%Y-%m-%d")
    msgs = []
    m = problem_message(command, rc, mine, _log_tail(command) if rc != 0 else None)
    if m: msgs.append(m)
    if command in ("b-check", "a-enter", "a-exit"):
        m = trade_message(command, run, b_row=L.last("b_days", day=day), a_row=L.last("a_windows", day=day),
                          equity_row=L.last("equity", strategy="B" if command == "b-check" else "A"))
        if m: msgs.append(m)
    if command == "dashboard":
        today = now.strftime("%Y-%m-%d")
        msgs.append(daily_message(now, L.rows("runs"), alerts, L.last("b_days", day=today), L.last("a_windows", day=today),
                                  L.last("equity", strategy="B"), L.last("equity", strategy="A"), _dashboard_json()))
    return msgs


def after_run(command, rc, since, now=None, settings=None, api=None):
    """Build and send. Exit code 0 = nothing to send or all sent, 3 = at least one message could not be sent."""
    msgs = build_after_run(command, rc, since, now)
    if not msgs: print("notify: nothing to send"); return 0
    failed = 0
    for m in msgs:
        try:
            send(m, settings, api); print("notify: sent:", m.splitlines()[0])
        except NotifyError as e:
            failed += 1; print("notify: NOT sent:", m.splitlines()[0], "|", e)
    return 3 if failed else 0


# ---------------------------------------------------------------- setup (laptop, interactive)
def store(path, values):
    """Set KEY=value lines in the secrets file (other lines untouched; file stays mode 600). Values never printed."""
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lines = p.read_text(encoding="utf-8").splitlines() if p.is_file() else []
    keep = [ln for ln in lines if ln.split("=", 1)[0].strip().removeprefix("export ").strip() not in values]
    keep += [f"{k}={v}" for k, v in values.items()]
    tmp = p.with_name(p.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(keep) + "\n")
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


TOKEN_RE = re.compile(r"\d{5,}:[A-Za-z0-9_-]{30,}")


def parse_token(raw):
    """The bot token inside whatever was pasted (spaces, quotes, a 'bot' prefix or the URL around it), or None."""
    m = TOKEN_RE.search((raw or "").replace(" ", "").replace("\t", ""))
    return m.group(0) if m else None


def find_chat(token, wait_s=180, api=None):
    """Wait for the first private message to the bot and return (chat_id, first_name)."""
    api = api or _api; deadline = time.time() + wait_s; offset = None
    while time.time() < deadline:
        params = {"timeout": 20, "allowed_updates": json.dumps(["message"])}
        if offset is not None: params["offset"] = offset
        for u in api(token, "getUpdates", params, timeout=30) or []:
            offset = u["update_id"] + 1
            chat = (u.get("message") or {}).get("chat") or {}
            if chat.get("type") == "private": return str(chat["id"]), chat.get("first_name", "")
    return None, None


def cmd_setup():
    p = Path(SECRETS_FILE); s = load_settings(p)
    print(f"Telegram setup. Settings go into {p} (mode 600), next to the Binance keys.")
    token, me = s.get("TELEGRAM_BOT_TOKEN"), None
    if token:
        print("A bot token is already stored: checking it.")
        try:
            me = _api(token, "getMe")
        except NotifyError as e:
            print("The stored token does not work:", e); return 1
    else:
        print("1. In Telegram, open @BotFather, send /newbot, pick a name and a username ending in 'bot'.")
        print("2. BotFather replies 'Done! Congratulations...'. Under 'Use this token to access the HTTP API:' is the")
        print("   token: digits, a colon, then about 35 letters/digits (e.g. 123456789:AAF...). Copy just that line and")
        print("   paste it here, then press Enter. Input is hidden: nothing appears while you paste. It is never shown.")
        for attempt in range(3):
            raw = getpass.getpass("Bot token: ")
            token = parse_token(raw)
            if not token:
                print(f"   That is not a bot token (received {len(raw.strip())} characters, no 'digits:letters' token in it). Try again.")
                continue
            try:
                me = _api(token, "getMe"); break
            except NotifyError as e:
                print("   Telegram does not accept it:", e, "(copy the token again from BotFather; /token there shows it)")
        if me is None: print("No working token: nothing changed."); return 1
    if not s.get("TELEGRAM_BOT_TOKEN"): store(p, {"TELEGRAM_BOT_TOKEN": token})
    print(f"Token OK: bot @{me.get('username')}")
    chat = s.get("TELEGRAM_CHAT_ID")
    if not chat:
        print(f"3. Open https://t.me/{me.get('username')} in Telegram and press Start (or send it any message). Waiting up to 3 minutes...")
        try:
            chat, name = find_chat(token)
        except NotifyError as e:
            print("Could not read the bot's messages:", e); return 1
        if not chat: print("No message arrived. Run `btc-bot notify setup` again."); return 1
        store(p, {"TELEGRAM_CHAT_ID": chat}); print(f"Chat found ({name}) and stored.")
    try:
        send(f"✅ BTC bot notifications set up ({socket.gethostname()}). Problems, trades and a daily summary at ~23:10 UTC "
             "will arrive here once the settings are on the server.", {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": chat})
    except NotifyError as e:
        print("Test message failed:", e); return 1
    print("Test message sent: check Telegram.")
    print("Last step, copy the settings to the server:  bash deploy/digitalocean/do.sh bot-keys")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Telegram notifications for the scheduled bot (see the module docstring).")
    sub = ap.add_subparsers(dest="action", required=True)
    sub.add_parser("setup", help="once, interactive: store the bot token and your chat id, send a test message")
    t = sub.add_parser("test", help="send a test message with the stored settings")
    t.add_argument("--text", default=None)
    r = sub.add_parser("after-run", help="called by bot-run.sh after each scheduled run")
    r.add_argument("--command", required=True, choices=list(SCHEDULED))
    r.add_argument("--rc", type=int, required=True, help="the run's exit code")
    r.add_argument("--since", required=True, help="run start, UTC, e.g. 2026-11-17T22:54:01Z (alerts and runs from then on)")
    r.add_argument("--now", default=None, help="replay: pretend it is this UTC time, e.g. '2026-11-17 23:10' (tests)")
    r.add_argument("--print-only", action="store_true", help="print the messages instead of sending them (preview)")
    a = ap.parse_args(argv)
    if a.action == "setup": return cmd_setup()
    if a.action == "test":
        try:
            send(a.text or f"✅ BTC bot test message from {socket.gethostname()} at {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
        except NotifyError as e:
            print("notify test: NOT sent:", e); return 3
        print("notify test: sent"); return 0
    now = datetime.strptime(a.now, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc) if a.now else None
    if a.print_only:
        msgs = build_after_run(a.command, a.rc, a.since, now)
        print("\n\n".join(msgs) if msgs else "(nothing to send)"); return 0
    return after_run(a.command, a.rc, a.since, now)


if __name__ == "__main__":
    sys.exit(main())
