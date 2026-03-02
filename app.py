from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

COINGECKO_SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_MARKET_CHART_URL = "https://api.coingecko.com/api/v3/coins/{coin}/market_chart"

DEFAULT_COIN = "bitcoin"
DEFAULT_CURRENCY = "usd"

INDICATORS = {"sma", "ema", "rsi", "macd"}
TIMEFRAMES = {
    "1m": {"days": "1", "loop_seconds": 15},
    "5m": {"days": "1", "loop_seconds": 25},
    "15m": {"days": "1", "loop_seconds": 35},
    "1h": {"days": "7", "loop_seconds": 45},
    "4h": {"days": "30", "loop_seconds": 60},
}

state_lock = threading.Lock()
bot_thread: threading.Thread | None = None

demo_account = {
    "balance_usd": 10000.0,
    "spot_holdings": {},
    "trade_history": [],
}

bot_state = {
    "running": False,
    "settings": {},
    "last_signal": "hold",
    "last_price": None,
    "last_error": "",
    "last_check_at": None,
    "open_position": None,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


def _request_json(url: str, params: dict[str, str]) -> dict | list:
    query = urlencode(params)
    full_url = f"{url}?{query}"
    request_obj = Request(
        full_url,
        headers={
            "accept": "application/json",
            "user-agent": "crypto-app-demo/2.0",
        },
    )
    with urlopen(request_obj, timeout=12) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def _fetch_coin_data(coin: str, currency: str) -> dict:
    data = _request_json(
        COINGECKO_SIMPLE_PRICE_URL,
        {
            "ids": coin,
            "vs_currencies": currency,
            "include_24hr_change": "true",
            "include_24hr_vol": "true",
            "include_market_cap": "true",
            "include_last_updated_at": "true",
        },
    )
    if not isinstance(data, dict):
        return {}
    return data.get(coin, {})


def _fetch_market_list(currency: str, limit: int) -> list[dict]:
    data = _request_json(
        COINGECKO_MARKETS_URL,
        {
            "vs_currency": currency,
            "order": "market_cap_desc",
            "per_page": str(limit),
            "page": "1",
            "sparkline": "false",
            "price_change_percentage": "24h",
        },
    )
    return data if isinstance(data, list) else []


def _fetch_price_series(coin: str, currency: str, days: str) -> list[float]:
    data = _request_json(
        COINGECKO_MARKET_CHART_URL.format(coin=coin),
        {
            "vs_currency": currency,
            "days": days,
        },
    )
    if not isinstance(data, dict):
        return []
    prices = data.get("prices")
    if not isinstance(prices, list):
        return []
    parsed: list[float] = []
    for pair in prices:
        if isinstance(pair, list) and len(pair) > 1:
            value = _safe_float(pair[1], 0.0)
            if value > 0:
                parsed.append(value)
    return parsed


def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2 / (period + 1)
    current = values[0]
    for value in values[1:]:
        current = (value * k) + (current * (1 - k))
    return current


def _indicator_signal(indicator: str, prices: list[float]) -> str:
    if len(prices) < 20:
        return "hold"

    latest_price = prices[-1]

    if indicator == "sma":
        window = prices[-14:]
        sma = sum(window) / len(window)
        return "buy" if latest_price >= sma else "sell"

    if indicator == "ema":
        ema_21 = _ema(prices[-60:], 21)
        return "buy" if latest_price >= ema_21 else "sell"

    if indicator == "rsi":
        closes = prices[-15:]
        gains = []
        losses = []
        for previous, current in zip(closes, closes[1:]):
            diff = current - previous
            if diff >= 0:
                gains.append(diff)
            else:
                losses.append(abs(diff))

        avg_gain = (sum(gains) / 14) if gains else 0.0
        avg_loss = (sum(losses) / 14) if losses else 0.0
        if avg_loss == 0 and avg_gain == 0:
            return "hold"
        if avg_loss == 0:
            return "sell"

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        if rsi <= 35:
            return "buy"
        if rsi >= 65:
            return "sell"
        return "hold"

    if indicator == "macd":
        if len(prices) < 35:
            return "hold"
        macd_line = _ema(prices[-120:], 12) - _ema(prices[-120:], 26)
        macd_series: list[float] = []
        for index in range(35, len(prices) + 1):
            subset = prices[:index]
            macd_series.append(_ema(subset, 12) - _ema(subset, 26))
        signal_line = _ema(macd_series[-45:], 9)
        return "buy" if macd_line >= signal_line else "sell"

    return "hold"


def _append_trade(trade: dict) -> None:
    demo_account["trade_history"].append(trade)
    if len(demo_account["trade_history"]) > 250:
        demo_account["trade_history"] = demo_account["trade_history"][-250:]


def _account_snapshot() -> dict:
    with state_lock:
        return {
            "balance_usd": round(demo_account["balance_usd"], 2),
            "spot_holdings": dict(demo_account["spot_holdings"]),
            "recent_trades": list(demo_account["trade_history"][-25:])[::-1],
        }


def _execute_spot_trade(coin: str, side: str, amount_usd: float, price: float) -> dict:
    if side not in {"buy", "sell"}:
        raise ValueError("Side 'buy' ya 'sell' honi chahiye.")
    if amount_usd <= 0:
        raise ValueError("Amount 0 se barha hona chahiye.")
    if price <= 0:
        raise ValueError("Invalid market price.")

    quantity = amount_usd / price

    with state_lock:
        current_balance = demo_account["balance_usd"]
        holdings = demo_account["spot_holdings"]
        coin_quantity = _safe_float(holdings.get(coin), 0.0)

        if side == "buy":
            if amount_usd > current_balance:
                raise ValueError("Demo balance kam hai.")
            demo_account["balance_usd"] = current_balance - amount_usd
            holdings[coin] = round(coin_quantity + quantity, 8)
        else:
            if quantity > coin_quantity:
                raise ValueError(f"{coin} holdings kam hain, pehle buy karein.")
            new_quantity = coin_quantity - quantity
            if new_quantity <= 0:
                holdings.pop(coin, None)
            else:
                holdings[coin] = round(new_quantity, 8)
            demo_account["balance_usd"] = current_balance + amount_usd

        trade = {
            "timestamp": _now_iso(),
            "trade_type": "manual_spot",
            "coin": coin,
            "side": side,
            "amount_usd": round(amount_usd, 2),
            "price": round(price, 6),
            "quantity": round(quantity, 8),
            "status": "filled",
        }
        _append_trade(trade)

        return {
            "trade": trade,
            "balance_usd": round(demo_account["balance_usd"], 2),
            "spot_holdings": dict(demo_account["spot_holdings"]),
        }


def _execute_futures_trade(coin: str, side: str, amount_usd: float, leverage: float, price: float) -> dict:
    if side not in {"buy", "sell"}:
        raise ValueError("Side 'buy' ya 'sell' honi chahiye.")
    if amount_usd <= 0:
        raise ValueError("Amount 0 se barha hona chahiye.")
    if leverage < 1 or leverage > 50:
        raise ValueError("Leverage 1 se 50 ke darmiyan honi chahiye.")
    if price <= 0:
        raise ValueError("Invalid market price.")

    notional = amount_usd * leverage
    fee = notional * 0.0006

    with state_lock:
        if fee > demo_account["balance_usd"]:
            raise ValueError("Demo balance fee ke liye kaafi nahi.")

        demo_account["balance_usd"] -= fee

        trade = {
            "timestamp": _now_iso(),
            "trade_type": "manual_futures",
            "coin": coin,
            "side": side,
            "amount_usd": round(amount_usd, 2),
            "leverage": leverage,
            "notional_usd": round(notional, 2),
            "entry_price": round(price, 6),
            "fee_usd": round(fee, 4),
            "status": "opened",
        }
        _append_trade(trade)

        return {
            "trade": trade,
            "balance_usd": round(demo_account["balance_usd"], 2),
        }


def _close_bot_position(reason: str, close_price: float) -> dict | None:
    position = bot_state.get("open_position")
    if not position:
        return None
    if close_price <= 0:
        return None

    side = position["side"]
    direction = 1 if side == "buy" else -1
    entry_price = _safe_float(position["entry_price"], 0.0)
    leverage = _safe_float(position["leverage"], 1.0)
    amount_usd = _safe_float(position["amount_usd"], 0.0)
    if entry_price <= 0 or amount_usd <= 0:
        bot_state["open_position"] = None
        return None

    price_move_pct = ((close_price - entry_price) / entry_price) * 100.0
    pnl_pct = price_move_pct * direction * leverage
    pnl_usd = amount_usd * (pnl_pct / 100.0)
    demo_account["balance_usd"] += pnl_usd

    close_trade = {
        "timestamp": _now_iso(),
        "trade_type": "bot_close",
        "coin": position["coin"],
        "side": side,
        "entry_price": round(entry_price, 6),
        "exit_price": round(close_price, 6),
        "amount_usd": round(amount_usd, 2),
        "leverage": leverage,
        "pnl_usd": round(pnl_usd, 4),
        "pnl_pct": round(pnl_pct, 4),
        "reason": reason,
        "status": "closed",
    }
    _append_trade(close_trade)
    bot_state["open_position"] = None
    return close_trade


def _run_bot() -> None:
    while True:
        with state_lock:
            if not bot_state["running"]:
                break
            settings = dict(bot_state["settings"])
            open_position = dict(bot_state["open_position"]) if bot_state["open_position"] else None

        timeframe = settings.get("timeframe", "5m")
        timeframe_cfg = TIMEFRAMES.get(timeframe, TIMEFRAMES["5m"])
        sleep_seconds = timeframe_cfg["loop_seconds"]

        try:
            coin = settings["coin"]
            currency = settings["currency"]
            indicator = settings["indicator"]
            take_profit = settings["take_profit_pct"]
            stop_loss = settings["stop_loss_pct"]

            market = _fetch_coin_data(coin=coin, currency=currency)
            current_price = _safe_float(market.get(currency), 0.0)
            prices = _fetch_price_series(coin=coin, currency=currency, days=timeframe_cfg["days"])
            signal = _indicator_signal(indicator, prices)

            with state_lock:
                bot_state["last_signal"] = signal
                bot_state["last_price"] = round(current_price, 6) if current_price > 0 else None
                bot_state["last_check_at"] = _now_iso()
                bot_state["last_error"] = ""

                if bot_state["open_position"]:
                    position = bot_state["open_position"]
                    side = position["side"]
                    direction = 1 if side == "buy" else -1
                    entry_price = _safe_float(position["entry_price"], 0.0)
                    leverage = _safe_float(position["leverage"], 1.0)
                    if current_price > 0 and entry_price > 0:
                        position_move_pct = ((current_price - entry_price) / entry_price) * 100
                        leveraged_pct = position_move_pct * direction * leverage
                        if leveraged_pct >= take_profit:
                            _close_bot_position("take_profit", current_price)
                        elif leveraged_pct <= -stop_loss:
                            _close_bot_position("stop_loss", current_price)
                        elif signal in {"buy", "sell"} and signal != side:
                            _close_bot_position("signal_flip", current_price)

                if bot_state["running"] and bot_state["open_position"] is None and signal in {"buy", "sell"}:
                    amount = _safe_float(settings.get("amount_usd"), 0.0)
                    if amount > demo_account["balance_usd"]:
                        bot_state["last_error"] = "Bot trade ke liye demo balance kam hai."
                    elif amount > 0 and current_price > 0:
                        bot_state["open_position"] = {
                            "opened_at": _now_iso(),
                            "coin": coin,
                            "side": signal,
                            "entry_price": round(current_price, 6),
                            "amount_usd": amount,
                            "leverage": _safe_float(settings.get("leverage"), 1.0),
                        }
                        _append_trade(
                            {
                                "timestamp": _now_iso(),
                                "trade_type": "bot_open",
                                "coin": coin,
                                "side": signal,
                                "entry_price": round(current_price, 6),
                                "amount_usd": round(amount, 2),
                                "leverage": _safe_float(settings.get("leverage"), 1.0),
                                "status": "opened",
                            }
                        )
        except Exception as exc:  # noqa: BLE001
            with state_lock:
                bot_state["last_error"] = str(exc)
                bot_state["last_check_at"] = _now_iso()

        time.sleep(sleep_seconds)


def _start_bot(settings: dict) -> None:
    global bot_thread
    with state_lock:
        bot_state["running"] = True
        bot_state["settings"] = settings
        bot_state["last_signal"] = "hold"
        bot_state["last_price"] = None
        bot_state["last_error"] = ""
        bot_state["last_check_at"] = _now_iso()
        bot_state["open_position"] = None

    bot_thread = threading.Thread(target=_run_bot, daemon=True)
    bot_thread.start()


@app.route("/")
def home():
    return render_template(
        "home.html",
        page_name="home",
        default_currency=DEFAULT_CURRENCY,
    )


@app.route("/btc")
def btc_realtime():
    return render_template("btc.html", page_name="btc")


@app.route("/trading")
def trading_home():
    return render_template("trading.html", page_name="trading")


@app.route("/trading/spot")
def trading_spot():
    return render_template(
        "spot.html",
        page_name="trading",
        default_coin=DEFAULT_COIN,
        default_currency=DEFAULT_CURRENCY,
    )


@app.route("/trading/futures")
def trading_futures():
    return render_template(
        "futures.html",
        page_name="trading",
        default_coin=DEFAULT_COIN,
        default_currency=DEFAULT_CURRENCY,
    )


@app.route("/trading/bot")
def trading_bot():
    return render_template(
        "bot.html",
        page_name="trading",
        default_coin=DEFAULT_COIN,
        default_currency=DEFAULT_CURRENCY,
    )


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "crypto-app-demo"})


@app.route("/api/account", methods=["GET"])
def api_account():
    return jsonify(_account_snapshot())


@app.route("/api/market", methods=["GET"])
def api_market():
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
            "fetched_at": _now_iso(),
        }
    )


@app.route("/api/markets", methods=["GET"])
def api_markets():
    try:
        currency = _normalize_currency(request.args.get("currency"))
        limit = int(request.args.get("limit", "30"))
    except ValueError:
        return jsonify({"error": "Invalid query params."}), 400

    limit = max(5, min(limit, 100))

    try:
        raw_markets = _fetch_market_list(currency=currency, limit=limit)
    except HTTPError as exc:
        return jsonify({"error": "Market provider error", "details": f"HTTP {exc.code}"}), 502
    except URLError:
        return jsonify({"error": "Provider se connection nahi ho saka."}), 503
    except json.JSONDecodeError:
        return jsonify({"error": "Provider ne invalid response diya."}), 502

    markets = []
    for item in raw_markets:
        if not isinstance(item, dict):
            continue
        markets.append(
            {
                "id": item.get("id"),
                "symbol": item.get("symbol"),
                "name": item.get("name"),
                "image": item.get("image"),
                "current_price": item.get("current_price"),
                "market_cap": item.get("market_cap"),
                "total_volume": item.get("total_volume"),
                "price_change_percentage_24h": item.get("price_change_percentage_24h"),
            }
        )

    return jsonify(
        {
            "currency": currency,
            "count": len(markets),
            "fetched_at": _now_iso(),
            "markets": markets,
        }
    )


@app.route("/api/trade/execute", methods=["POST"])
def api_trade_execute():
    payload = request.get_json(silent=True) or {}

    try:
        market_type = (payload.get("market_type") or "spot").strip().lower()
        coin = _normalize_coin_id(payload.get("coin"))
        currency = _normalize_currency(payload.get("currency"))
        side = (payload.get("side") or "").strip().lower()
        amount_usd = _safe_float(payload.get("amount_usd"), 0.0)
        leverage = _safe_float(payload.get("leverage"), 1.0)
        if currency != "usd":
            raise ValueError("Filhal demo trading sirf USD currency support karti hai.")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        market = _fetch_coin_data(coin=coin, currency=currency)
        price = _safe_float(market.get(currency), 0.0)
        if price <= 0:
            return jsonify({"error": "Coin price fetch nahi ho saki."}), 502
    except HTTPError as exc:
        return jsonify({"error": "Market provider error", "details": f"HTTP {exc.code}"}), 502
    except URLError:
        return jsonify({"error": "Provider se connection nahi ho saka."}), 503
    except json.JSONDecodeError:
        return jsonify({"error": "Provider ne invalid response diya."}), 502

    try:
        if market_type == "spot":
            result = _execute_spot_trade(coin=coin, side=side, amount_usd=amount_usd, price=price)
        elif market_type == "futures":
            result = _execute_futures_trade(
                coin=coin,
                side=side,
                amount_usd=amount_usd,
                leverage=leverage,
                price=price,
            )
        else:
            return jsonify({"error": "market_type sirf spot ya futures ho sakta hai."}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(result)


@app.route("/api/bot/start", methods=["POST"])
def api_bot_start():
    payload = request.get_json(silent=True) or {}

    try:
        coin = _normalize_coin_id(payload.get("coin"))
        currency = _normalize_currency(payload.get("currency"))
        timeframe = (payload.get("timeframe") or "5m").strip().lower()
        indicator = (payload.get("indicator") or "sma").strip().lower()
        leverage = _safe_float(payload.get("leverage"), 1.0)
        amount_usd = _safe_float(payload.get("amount_usd"), 0.0)
        take_profit_pct = _safe_float(payload.get("take_profit_pct"), 2.0)
        stop_loss_pct = _safe_float(payload.get("stop_loss_pct"), 1.0)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if timeframe not in TIMEFRAMES:
        return jsonify({"error": "Invalid timeframe. 1m, 5m, 15m, 1h, 4h allowed."}), 400
    if indicator not in INDICATORS:
        return jsonify({"error": "Invalid indicator. sma/ema/rsi/macd allowed."}), 400
    if leverage < 1 or leverage > 20:
        return jsonify({"error": "Leverage 1 se 20 ke darmiyan rakhein."}), 400
    if amount_usd <= 0:
        return jsonify({"error": "Amount 0 se barha hona chahiye."}), 400
    if take_profit_pct <= 0 or stop_loss_pct <= 0:
        return jsonify({"error": "Take profit aur stop loss positive honi chahiye."}), 400
    if currency != "usd":
        return jsonify({"error": "Filhal bot currency sirf USD support karti hai."}), 400

    with state_lock:
        if bot_state["running"]:
            return jsonify({"error": "Bot pehle se running hai."}), 409
        if amount_usd > demo_account["balance_usd"]:
            return jsonify({"error": "Demo balance bot amount se kam hai."}), 400

    settings = {
        "coin": coin,
        "currency": currency,
        "timeframe": timeframe,
        "indicator": indicator,
        "leverage": leverage,
        "amount_usd": amount_usd,
        "take_profit_pct": take_profit_pct,
        "stop_loss_pct": stop_loss_pct,
    }
    _start_bot(settings)
    return jsonify({"message": "Bot start ho gaya.", "settings": settings})


@app.route("/api/bot/stop", methods=["POST"])
def api_bot_stop():
    with state_lock:
        if not bot_state["running"]:
            return jsonify({"message": "Bot pehle hi stopped hai."})
        bot_state["running"] = False
        close_price = _safe_float(bot_state.get("last_price"), 0.0)
        if bot_state.get("open_position") and close_price > 0:
            _close_bot_position("manual_stop", close_price)

    return jsonify({"message": "Bot stop kar diya gaya."})


@app.route("/api/bot/status", methods=["GET"])
def api_bot_status():
    with state_lock:
        bot_trades = [trade for trade in demo_account["trade_history"] if str(trade.get("trade_type", "")).startswith("bot_")]
        return jsonify(
            {
                "running": bot_state["running"],
                "settings": dict(bot_state["settings"]),
                "last_signal": bot_state["last_signal"],
                "last_price": bot_state["last_price"],
                "last_error": bot_state["last_error"],
                "last_check_at": bot_state["last_check_at"],
                "open_position": dict(bot_state["open_position"]) if bot_state["open_position"] else None,
                "balance_usd": round(demo_account["balance_usd"], 2),
                "recent_bot_trades": list(bot_trades[-20:])[::-1],
            }
        )


@app.route("/balance", methods=["GET"])
def legacy_balance():
    return jsonify(_account_snapshot())


@app.route("/trade", methods=["POST"])
def legacy_trade():
    payload = request.get_json(silent=True) or {}
    trade_payload = {
        "market_type": payload.get("market_type", "spot"),
        "coin": payload.get("coin", DEFAULT_COIN),
        "currency": payload.get("currency", "usd"),
        "side": payload.get("side", "buy"),
        "amount_usd": payload.get("amount_usd", payload.get("amount")),
        "leverage": payload.get("leverage", 1),
    }

    try:
        market_type = (trade_payload.get("market_type") or "spot").strip().lower()
        coin = _normalize_coin_id(trade_payload.get("coin"))
        currency = _normalize_currency(trade_payload.get("currency"))
        side = (trade_payload.get("side") or "").strip().lower()
        amount_usd = _safe_float(trade_payload.get("amount_usd"), 0.0)
        leverage = _safe_float(trade_payload.get("leverage"), 1.0)
        if currency != "usd":
            raise ValueError("Filhal demo trading sirf USD currency support karti hai.")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        market = _fetch_coin_data(coin=coin, currency=currency)
        price = _safe_float(market.get(currency), 0.0)
        if price <= 0:
            return jsonify({"error": "Coin price fetch nahi ho saki."}), 502
    except HTTPError as exc:
        return jsonify({"error": "Market provider error", "details": f"HTTP {exc.code}"}), 502
    except URLError:
        return jsonify({"error": "Provider se connection nahi ho saka."}), 503
    except json.JSONDecodeError:
        return jsonify({"error": "Provider ne invalid response diya."}), 502

    try:
        if market_type == "spot":
            result = _execute_spot_trade(coin=coin, side=side, amount_usd=amount_usd, price=price)
        elif market_type == "futures":
            result = _execute_futures_trade(
                coin=coin,
                side=side,
                amount_usd=amount_usd,
                leverage=leverage,
                price=price,
            )
        else:
            return jsonify({"error": "market_type sirf spot ya futures ho sakta hai."}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
