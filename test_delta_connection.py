import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from dotenv import load_dotenv
from src.exchange.delta_client import DeltaExchangeClient, DeltaAPIException, DeltaSecurityException


def mask_str(s: str, show_chars: int = 4) -> str:
    if not s:
        return "<NOT CONFIGURED>"
    if len(s) <= show_chars * 2:
        return "*" * len(s)
    return s[:show_chars] + "*" * (len(s) - (show_chars * 2)) + s[-show_chars:]


def main():
    print("=" * 60)
    print("        DELTA DEMO / TESTNET CONNECTION TEST")
    print("=" * 60)

    env_file = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_file):
        load_dotenv(env_file)

    environment = os.getenv("DELTA_ENVIRONMENT", "testnet").lower().strip()
    base_url = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org").strip()
    api_key = os.getenv("DELTA_API_KEY", "").strip()
    api_secret = os.getenv("DELTA_API_SECRET", "").strip()
    symbol = os.getenv("SYMBOL", "BTCUSD").strip()

    print(f"Environment : {environment.upper()}")
    print(f"Base URL    : {base_url}")
    print(f"API Key     : {mask_str(api_key)}")
    print(f"API Secret  : {mask_str(api_secret)}")
    print(f"Test Symbol : {symbol}")
    print("-" * 60)

    client = DeltaExchangeClient(
        api_key=api_key,
        api_secret=api_secret,
        environment=environment,
        base_url=base_url,
        trading_enabled=False,
    )

    try:
        t0 = time.time()
        ticker = client.get_ticker(symbol)
        latency = (time.time() - t0) * 1000
        mark_price = float(ticker.get("mark_price") or ticker.get("close") or 0.0)
        print(f"[OK] Public Market Data: Connected to Delta Testnet ({latency:.1f}ms)")
        print(f"     Mark Price for {symbol}: ${mark_price:,.2f}")
    except Exception as e:
        print(f"[FAIL] Public Market Data: {e}")
        return

    if api_key and api_secret:
        try:
            balances = client.get_wallet_balance_dict()
            print(f"[OK] Authenticated REST API: Signature Verified")
            for asset, b in balances.items():
                if b["balance"] > 0:
                    print(f"     {asset}: {b['balance']} (Available: {b['available']})")
        except Exception as e:
            print(f"[FAIL] Authenticated API: {e}")
    else:
        print("[INFO] Authenticated checks skipped (API Key / Secret not provided).")

    print("=" * 60)
    print("Diagnostic completed.")


if __name__ == "__main__":
    main()
