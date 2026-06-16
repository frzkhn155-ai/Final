# Upstox Static-IP Restriction (`UDAPI1154`) — Why No Orders Get Placed

## Symptom

The bot logs show **every order rejected with HTTP 403** and this error body:

```json
{"status":"error","errors":[{"errorCode":"UDAPI1154",
 "message":"Access to this API is blocked due to static IP restrictions. Reason: No static IP has been configured."}]}
```

In the trade logs you see signals and "PLACING … ORDER" lines, but each is followed by:

```
⚠ ORB order failed for TVSMOTOR
```

`exits_log.csv` / `positions_tracking.csv` stay empty and there are **zero fills**.
The OAuth token itself is valid — `verify_token()` treats a 403 here as
"token valid, IP blocked" (see `Both4withcache10_headless.py`, the `status_code == 403`
branch of token verification). The block is purely an **IP allow-list** problem.

## Root Cause

Upstox lets you (optionally) restrict an API app so order/trade endpoints only
work from a **whitelisted static IP**. When that setting is on but the caller's
IP is not on the list, Upstox returns `UDAPI1154` and refuses the order.

The bot runs on **GitHub Actions hosted runners**, whose outbound IP changes on
every run and is not static. So the runner IP can never match an Upstox
whitelist → every order is blocked. Read-only/market-data calls keep working,
which is why the bot *looks* healthy and still produces signals.

## Fix — pick ONE

### Option A — Turn OFF static-IP restriction (simplest)
1. Go to <https://account.upstox.com/developer/apps>.
2. Open the app whose API key the bot uses (`UPSTOX_API_KEY`).
3. Disable / clear the **static IP** (IP allow-list) setting and save.
4. Re-run the workflow. Orders should now place from any IP.

Trade-off: the app can place orders from any IP using a valid token. Keep the
token (`UPSTOX_TOKEN`) and API secret in GitHub Secrets only.

### Option B — Keep the restriction, give the bot a fixed IP
Use this if your account/compliance requires a static IP. You must route the
bot's outbound traffic through one stable IP and whitelist it in the Upstox app.

1. Provision a static egress IP, e.g. one of:
   - A small always-on VM/VPS (DigitalOcean, AWS Lightsail, etc.) with a static IP, or
   - A static-IP HTTP/SOCKS proxy / NAT gateway, or
   - A VPN that exits via a fixed IP.
2. Whitelist that IP in the Upstox app settings.
3. Make the bot use it:
   - **Self-hosted runner** on the static-IP VM — change the workflow job to
     `runs-on: self-hosted` and run the GitHub Actions runner agent on that VM. All
     API calls then originate from the VM's static IP. (Recommended.)
   - **Or proxy the requests** — set `HTTPS_PROXY` / `HTTP_PROXY` env vars (stored
     as GitHub Secrets) on the "Run trading bot" step so `requests` egresses through
     the static-IP proxy.

## How to confirm it's fixed
Re-run the workflow during market hours and check the run log:
- Before: `📥 ORDER RESPONSE (403): … UDAPI1154 …`
- After:  `📥 ORDER RESPONSE (200): … "status":"success" …` and rows appear in
  `orb_trades.csv` / `positions_tracking.csv` / `exits_log.csv`.

## Note
Until this is resolved, the bot is effectively **signal-only**: it detects and
logs setups but cannot execute. Any realised P&L on those symbols would come
from a **manual** trade taken off the bot's alerts, not from the bot itself.
