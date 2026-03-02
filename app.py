from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

COINGECKO_SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
DEFAULT_COIN = "bitcoin"
DEFAULT_CURRENCY = "usd"

user_data = {
    "balance": 10000,
    "trades": []
}


def _normalize_coin_id(raw_coin: str | None) -> str:
    coin = (raw_coin or DEFAULT_COIN).strip().lower()
    if not coin:
        coin = DEFAULT_COIN
    if not coin.replace("-", "").isalnum():
        raise ValueError("Coin ID mein sirf letters, numbers ya hyphen use karo.")
    return coin


def _normalize_currency(raw_currency: str | None) -> str:
    currency = (raw_currency or DEFAULT_CURRENCY).strip().lower()
    if not currency.isalpha():
        raise ValueError("Currency code sirf letters par mushtamil hona chahiye.")
    return currency


def _fetch_coin_data(coin: str, currency: str) -> dict:
    params = {
        "ids": coin,
        "vs_currencies": currency,
        "include_24hr_change": "true",
        "include_24hr_vol": "true",
        "include_market_cap": "true",
        "include_last_updated_at": "true",
    }
    url = f"{COINGECKO_SIMPLE_PRICE_URL}?{urlencode(params)}"
    request_obj = Request(
        url,
        headers={
            "accept": "application/json",
            "user-agent": "crypto-app-demo/1.0",
        },
    )
    with urlopen(request_obj, timeout=12) as response:
        payload = response.read().decode("utf-8")
    parsed = json.loads(payload)
    return parsed.get(coin, {})


@app.route("/")
def index():
    return render_template(
        "index.html",
        default_coin=DEFAULT_COIN,
        default_currency=DEFAULT_CURRENCY,
    )


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "crypto-app-demo"})


@app.route("/api/market", methods=["GET"])
def market_data():
    try:
        coin = _normalize_coin_id(request.args.get("coin"))
        currency = _normalize_currency(request.args.get("currency"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        data = _fetch_coin_data(coin=coin, currency=currency)
    except HTTPError as exc:
        return jsonify({"error": "Market provider error", "details": f"HTTP {exc.code}"}), 502
    except URLError:
        return jsonify({"error": "Provider se connection nahi ho saka."}), 503
    except json.JSONDecodeError:
        return jsonify({"error": "Provider ne invalid response diya."}), 502

    if not data:
        return jsonify({"error": "Coin data nahi mili. Coin ID check karo."}), 404

    return jsonify(
        {
            "coin": coin,
            "currency": currency,
            "price": data.get(currency),
            "change_24h": data.get(f"{currency}_24h_change"),
            "volume_24h": data.get(f"{currency}_24h_vol"),
            "market_cap": data.get(f"{currency}_market_cap"),
            "provider_updated_at": data.get("last_updated_at"),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    )


@app.route("/balance", methods=["GET"])
def get_balance():
    return jsonify(user_data)

@app.route("/trade", methods=["POST"])
def make_trade():
    data = request.json
    amount = data.get("amount")
    coin = data.get("coin")
    side = data.get("side")

    trade = {
        "coin": coin,
        "amount": amount,
        "side": side
    }
    user_data["trades"].append(trade)
    return jsonify({"message": "Trade successful", "trade": trade})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
