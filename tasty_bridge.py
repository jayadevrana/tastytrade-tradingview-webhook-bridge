#!/usr/bin/env python3
"""TastyTrade webhook bridge — TradingView alerts -> TastyTrade orders.

OAuth2 (personal grant). Client self-configures via web dashboard at /.
Credentials stored in /opt/tasty-bridge/credentials.json (chmod 600).

Env vars (/etc/tasty-bridge.env):
  TASTY_ENV      = cert | prod
  WEBHOOK_SECRET = shared secret required in every alert payload
"""
import json
import logging
import os
import threading
import time

import requests
from flask import Flask, jsonify, redirect, render_template_string, request

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("tasty-bridge")

TASTY_ENV = os.environ.get("TASTY_ENV", "cert")
BASE = ("https://api.cert.tastyworks.com" if TASTY_ENV == "cert"
        else "https://api.tastyworks.com")
SECRET = os.environ["WEBHOOK_SECRET"]
CRED_FILE = "/opt/tasty-bridge/credentials.json"

app = Flask(__name__)
_lock = threading.Lock()
_creds = None          # {client_secret, refresh_token, account}
_access_token = None
_token_exp = 0


def _load_creds():
    global _creds
    if os.path.exists(CRED_FILE):
        with open(CRED_FILE) as f:
            _creds = json.load(f)


def _save_creds(c):
    global _creds
    with open(CRED_FILE, "w") as f:
        json.dump(c, f)
    os.chmod(CRED_FILE, 0o600)
    _creds = c


def _refresh_access_token():
    global _access_token, _token_exp
    r = requests.post(f"{BASE}/oauth/token", json={
        "grant_type": "refresh_token",
        "refresh_token": _creds["refresh_token"],
        "client_secret": _creds["client_secret"],
    }, timeout=15)
    r.raise_for_status()
    d = r.json()
    _access_token = d["access_token"]
    _token_exp = time.time() + int(d.get("expires_in", 900)) - 60
    log.info("access token refreshed")


def _headers():
    with _lock:
        if _access_token is None or time.time() > _token_exp:
            _refresh_access_token()
    return {"Authorization": f"Bearer {_access_token}",
            "Content-Type": "application/json"}


def _api(method, path, payload=None):
    return requests.request(method, f"{BASE}{path}", headers=_headers(),
                            json=payload, timeout=20)


def get_position_qty(symbol):
    r = _api("GET", f"/accounts/{_creds['account']}/positions")
    r.raise_for_status()
    for p in r.json()["data"]["items"]:
        if p["symbol"] == symbol and p["instrument-type"] == "Equity":
            qty = float(p["quantity"])
            return -qty if p["quantity-direction"] == "Short" else qty
    return 0.0


def place_equity_market(symbol, action, qty):
    order = {
        "time-in-force": "Day",
        "order-type": "Market",
        "legs": [{"instrument-type": "Equity", "symbol": symbol,
                  "quantity": qty, "action": action}],
    }
    r = _api("POST", f"/accounts/{_creds['account']}/orders", order)
    body = r.json()
    log.info("order %s %s x%s -> %s %s", action, symbol, qty,
             r.status_code, json.dumps(body))
    return r.status_code, body


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TastyTrade Bridge</title><style>
body{font-family:-apple-system,Segoe UI,sans-serif;background:#0f1420;color:#e8ecf3;
 max-width:720px;margin:40px auto;padding:0 20px}
.card{background:#1a2233;border:1px solid #2a3550;border-radius:12px;padding:24px;margin:16px 0}
h1{font-size:22px}h2{font-size:16px;color:#9fb3d9}
input{width:100%;box-sizing:border-box;padding:10px;margin:6px 0 14px;border-radius:8px;
 border:1px solid #2a3550;background:#0f1420;color:#e8ecf3;font-family:monospace}
button{background:#4f8cff;color:#fff;border:0;padding:12px 24px;border-radius:8px;
 font-size:15px;cursor:pointer}button:hover{background:#3a76e8}
pre{background:#0f1420;border:1px solid #2a3550;border-radius:8px;padding:12px;
 overflow-x:auto;font-size:13px}
.ok{color:#4ade80}.err{color:#f87171}
.badge{display:inline-block;background:#173325;color:#4ade80;border:1px solid #2c5a40;
 padding:2px 10px;border-radius:20px;font-size:12px}
.badge.red{background:#331717;color:#f87171;border-color:#5a2c2c}
small{color:#7d8db0}</style></head><body>
<h1>🌉 TastyTrade Automation Bridge <span class="badge {{env_badge}}">{{env_label}}</span></h1>

{% if not connected %}
<div class="card">
<h2>Connect your TastyTrade sandbox account</h2>
<p><small>Credentials are stored only on this server and used only to talk to
TastyTrade's API. Get them at developer.tastytrade.com → OAuth Applications →
Manage → Create Grant (scopes: read, trade).</small></p>
{% if error %}<p class="err">✗ {{error}}</p>{% endif %}
<form method="post" action="/connect">
<label>Client Secret</label>
<input name="client_secret" required placeholder="your OAuth application client secret">
<label>Refresh Token</label>
<input name="refresh_token" required placeholder="eyJhbGciOi...">
<button type="submit">Connect</button>
</form></div>
{% else %}
<div class="card"><h2>Status</h2>
<p class="ok">✓ Connected — account <b>{{account}}</b> ({{env_label}})</p></div>

<div class="card"><h2>Webhook URL (paste into TradingView alert)</h2>
<pre>{{webhook_url}}</pre></div>

<div class="card"><h2>Alert message syntax (TradingView → Message box)</h2>
<p><b>BUY</b></p>
<pre>{"secret": "{{whsecret}}", "action": "buy", "symbol": "AAPL", "qty": 10}</pre>
<p><b>SELL (short)</b></p>
<pre>{"secret": "{{whsecret}}", "action": "sell", "symbol": "AAPL", "qty": 10}</pre>
<p><b>EXIT (close entire position — no qty needed)</b></p>
<pre>{"secret": "{{whsecret}}", "action": "exit", "symbol": "AAPL"}</pre>
<p><small>Market orders, Day time-in-force, US equities. "buy" while short
covers first; "sell" while long closes first; "exit" flattens. Use
TradingView placeholders like {{tv_qty}} and {{tv_sym}} to fill from your
strategy.</small></p></div>
{% endif %}
</body></html>"""


def _render(error=None):
    return render_template_string(
        PAGE,
        connected=_creds is not None,
        account=_creds.get("account") if _creds else None,
        env_label="SANDBOX" if TASTY_ENV == "cert" else "LIVE",
        env_badge="" if TASTY_ENV == "cert" else "red",
        webhook_url=f"http://{request.host}/webhook",
        whsecret=SECRET,
        error=error,
        tv_qty="{{strategy.order.contracts}}",
        tv_sym="{{ticker}}",
    )


@app.route("/")
def home():
    return _render()


@app.route("/connect", methods=["POST"])
def connect():
    global _access_token
    cs = request.form.get("client_secret", "").strip()
    rt = request.form.get("refresh_token", "").strip()
    if not cs or not rt:
        return _render("Both fields required"), 400
    # validate against tastytrade
    r = requests.post(f"{BASE}/oauth/token", json={
        "grant_type": "refresh_token",
        "refresh_token": rt, "client_secret": cs}, timeout=15)
    if r.status_code != 200:
        log.warning("connect failed: %s %s", r.status_code, r.text[:300])
        return _render(f"TastyTrade rejected credentials ({r.status_code}). "
                       "Check client secret and refresh token."), 400
    tok = r.json()["access_token"]
    ra = requests.get(f"{BASE}/customers/me/accounts",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    if ra.status_code != 200:
        return _render("Token valid but could not list accounts "
                       f"({ra.status_code}). Grant needs 'read' scope."), 400
    items = ra.json()["data"]["items"]
    if not items:
        return _render("No accounts found on this login."), 400
    account = items[0]["account"]["account-number"]
    _save_creds({"client_secret": cs, "refresh_token": rt, "account": account})
    with _lock:
        _access_token = None  # force fresh token from saved creds
    log.info("connected account %s", account)
    return redirect("/")


@app.route("/health")
def health():
    return jsonify(ok=True, env=TASTY_ENV,
                   connected=_creds is not None,
                   account=_creds.get("account") if _creds else None)


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify(error="invalid json"), 400
    if not data or data.get("secret") != SECRET:
        log.warning("bad secret from %s", request.remote_addr)
        return jsonify(error="unauthorized"), 401
    if _creds is None:
        return jsonify(error="bridge not connected yet — open dashboard"), 503

    action = str(data.get("action", "")).lower()
    symbol = str(data.get("symbol", "")).upper().strip()
    try:
        qty = int(float(data.get("qty", 0)))
    except (TypeError, ValueError):
        qty = 0

    if action not in ("buy", "sell", "exit"):
        return jsonify(error="action must be buy/sell/exit"), 400
    if not symbol:
        return jsonify(error="symbol required"), 400
    if action in ("buy", "sell") and qty <= 0:
        return jsonify(error="qty must be > 0"), 400

    try:
        pos = get_position_qty(symbol)
        results = []
        if action == "exit":
            if pos > 0:
                results.append(place_equity_market(symbol, "Sell to Close", int(pos)))
            elif pos < 0:
                results.append(place_equity_market(symbol, "Buy to Close", int(-pos)))
            else:
                return jsonify(status="flat, nothing to exit", symbol=symbol)
        elif action == "buy":
            if pos < 0:
                results.append(place_equity_market(symbol, "Buy to Close", int(-pos)))
            results.append(place_equity_market(symbol, "Buy to Open", qty))
        elif action == "sell":
            if pos > 0:
                results.append(place_equity_market(symbol, "Sell to Close", int(pos)))
            results.append(place_equity_market(symbol, "Sell to Open", qty))

        ok = all(code in (200, 201) for code, _ in results)
        return jsonify(status="ok" if ok else "error",
                       orders=[b for _, b in results]), (200 if ok else 502)
    except Exception as e:
        log.exception("order failed")
        return jsonify(error=str(e)), 500


_load_creds()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8899)
