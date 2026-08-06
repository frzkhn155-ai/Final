"""Simple CLI wrapper to run the scanner using the example YFinance provider.

Copy scanner/config_example.json to scanner/config.json and edit symbols or set env vars.
"""

import json
import os
import sys
from scanner.signal_scanner import (
    SignalScanner,
    YFinanceDataProvider,
    ConsoleAlertHandler,
    WebhookAlertHandler,
)

CONFIG_PATH = "scanner/config.json"


def load_config(path: str = CONFIG_PATH):
    if not os.path.exists(path):
        print(f"Config not found at {path}. Copy scanner/config_example.json to scanner/config.json and edit.")
        sys.exit(1)
    with open(path, "r") as f:
        return json.load(f)


def main():
    cfg = load_config()
    symbols = cfg.get("symbols", [])
    if not symbols:
        print("No symbols configured in config.json")
        sys.exit(1)

    # Choose alert handler
    webhook = cfg.get("webhook_url")
    if webhook:
        ah = WebhookAlertHandler(webhook)
    else:
        ah = ConsoleAlertHandler()

    # Data provider
    dp = YFinanceDataProvider()

    scanner = SignalScanner(
        symbols=symbols,
        data_provider=dp,
        alert_handler=ah,
        buffer_pct=cfg.get("buffer_pct", 0.0015),
        confirm_required=cfg.get("confirm_required", 2),
        state_path=cfg.get("state_path", "scanner/alert_state.json"),
    )

    interval = int(cfg.get("scan_interval_seconds", 30))
    scanner.run_loop(interval_seconds=interval)


if __name__ == "__main__":
    main()
