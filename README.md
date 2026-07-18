# TastyTrade TradingView Webhook Bridge

Single-file Flask bridge that turns TradingView alerts into live TastyTrade equity orders using OAuth2 personal grant, with a self-serve web dashboard for credential setup.

## Features

- Converts TradingView webhook alerts into TastyTrade market orders (US equities).
- Self-serve web dashboard at `/` to connect your TastyTrade account — no config files to edit by hand.
- OAuth2 personal-grant flow with automatic access-token refresh and expiry handling.
- Position-aware order logic: `buy`, `sell`, and `exit` actions auto-close opposing positions before opening new ones.
- Shared-secret authentication on every webhook payload to block unauthorized alerts.
- Sandbox (`cert`) and live (`prod`) environments switchable via a single env var, with a clear SANDBOX/LIVE badge in the dashboard.
- Credentials persisted server-side only, written with `chmod 600`.
- Built-in `/health` endpoint for uptime checks.

## Stack

- Python 3
- Flask (web dashboard + webhook endpoint)
- requests (TastyTrade REST API client)

## Getting started

```bash
pip install -r requirements.txt

# configure environment (see .env.example)
export TASTY_ENV=cert
export WEBHOOK_SECRET="a-long-random-string"

python tasty_bridge.py
```

The server listens on port `8899`. Open `http://<host>:8899/` and connect your
TastyTrade account (client secret + refresh token from
developer.tastytrade.com → OAuth Applications → Manage → Create Grant, scopes
`read` and `trade`). Then paste the shown webhook URL and alert JSON into your
TradingView alerts.

Example alert message:

```json
{"secret": "your-webhook-secret", "action": "buy", "symbol": "AAPL", "qty": 10}
```

Supported actions: `buy`, `sell` (short), and `exit` (flatten the position).

## Notes

Trading automation is infrastructure, not financial advice. No profit
guarantees. Test in the `cert` sandbox / paper environment before going live.

## Author

Built by [Jayadev Rana](https://jayadevrana.in) — @bluealgocapital · [YouTube](https://www.youtube.com/@jayadevrana3657) · [GitHub](https://github.com/jayadevrana)
