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
COINGECKO_OHLC_URL = "https://api.coingecko.com/api/v3/coins/{coin}/ohlc"
COINGECKO_COINS_LIST_URL = "https://api.coingecko.com/api/v3/coins/list"

DEFAULT_COIN = "bitcoin"
DEFAULT_CURRENCY = "usd"
SPOT_FEE_RATE = 0.001
FUTURES_FEE_RATE_OPEN = 0.0006
FUTURES_FEE_RATE_CLOSE = 0.0006
BOT_FEE_RATE_OPEN = 0.0006
BOT_FEE_RATE_CLOSE = 0.0006

INDICATORS = {"sma", "ema", "rsi", "macd"}
TIMEFRAMES = {
    "1m": {"days": "1", "loop_seconds": 30},
    "5m": {"days": "1", "loop_seconds": 55},
    "15m": {"days": "1", "loop_seconds": 70},
    "1h": {"days": "7", "loop_seconds": 90},
    "4h": {"days": "30", "loop_seconds": 120},
}

COIN_OPTIONS = [
    {"id": "bitcoin", "label": "Bitcoin (BTC)", "tv_symbol": "BINANCE:BTCUSDT"},
    {"id": "ethereum", "label": "Ethereum (ETH)", "tv_symbol": "BINANCE:ETHUSDT"},
    {"id": "tether", "label": "Tether (USDT)", "tv_symbol": "BINANCE:USDCUSDT"},
    {"id": "ripple", "label": "XRP", "tv_symbol": "BINANCE:XRPUSDT"},
    {"id": "binancecoin", "label": "BNB", "tv_symbol": "BINANCE:BNBUSDT"},
    {"id": "solana", "label": "Solana (SOL)", "tv_symbol": "BINANCE:SOLUSDT"},
    {"id": "usd-coin", "label": "USD Coin (USDC)", "tv_symbol": "BINANCE:USDCUSDT"},
    {"id": "dogecoin", "label": "Dogecoin (DOGE)", "tv_symbol": "BINANCE:DOGEUSDT"},
    {"id": "cardano", "label": "Cardano (ADA)", "tv_symbol": "BINANCE:ADAUSDT"},
    {"id": "tron", "label": "Tron (TRX)", "tv_symbol": "BINANCE:TRXUSDT"},
    {"id": "chainlink", "label": "Chainlink (LINK)", "tv_symbol": "BINANCE:LINKUSDT"},
    {"id": "avalanche-2", "label": "Avalanche (AVAX)", "tv_symbol": "BINANCE:AVAXUSDT"},
    {"id": "toncoin", "label": "Toncoin (TON)", "tv_symbol": "BINANCE:TONUSDT"},
    {"id": "stellar", "label": "Stellar (XLM)", "tv_symbol": "BINANCE:XLMUSDT"},
    {"id": "polkadot", "label": "Polkadot (DOT)", "tv_symbol": "BINANCE:DOTUSDT"},
    {"id": "sui", "label": "Sui (SUI)", "tv_symbol": "BINANCE:SUIUSDT"},
    {"id": "litecoin", "label": "Litecoin (LTC)", "tv_symbol": "BINANCE:LTCUSDT"},
    {"id": "bitcoin-cash", "label": "Bitcoin Cash (BCH)", "tv_symbol": "BINANCE:BCHUSDT"},
    {"id": "shiba-inu", "label": "Shiba Inu (SHIB)", "tv_symbol": "BINANCE:SHIBUSDT"},
    {"id": "pepe", "label": "Pepe (PEPE)", "tv_symbol": "BINANCE:PEPEUSDT"},
]

state_lock = threading.Lock()
bot_thread: threading.Thread | None = None
cache_lock = threading.Lock()
response_cache: dict[str, dict] = {}

demo_account = {
    "balance_usd": 10000.0,
    "spot_holdings": {},
    "futures_positions": [],
    "next_position_id": 1,
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


def _cache_get_fresh(key: str, max_age_seconds: int):
    now = time.time()
    with cache_lock:
        entry = response_cache.get(key)
        if not entry:
            return None
        if now - entry["stored_at"] > max_age_seconds:
            return None
        return entry["value"]


def _cache_get_stale(key: str):
    with cache_lock:
        entry = response_cache.get(key)
        if not entry:
            return None
        return entry["value"]


def _cache_set(key: str, value) -> None:
    with cache_lock:
        response_cache[key] = {"stored_at": time.time(), "value": value}


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
    cache_key = f"simple:{coin}:{currency}"
    fresh = _cache_get_fresh(cache_key, 15)
    if fresh is not None:
        return fresh

    try:
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
    except HTTPError as exc:
        if exc.code == 429:
            stale = _cache_get_stale(cache_key)
            if stale is not None:
                return stale
        raise

    if not isinstance(data, dict):
        return {}
    parsed = data.get(coin, {})
    if isinstance(parsed, dict) and parsed:
        _cache_set(cache_key, parsed)
    return parsed


def _fetch_market_list(currency: str, limit: int, page: int = 1) -> list[dict]:
    cache_key = f"markets:{currency}:{limit}:{page}"
    fresh = _cache_get_fresh(cache_key, 120)
    if fresh is not None:
        return fresh

    try:
        data = _request_json(
            COINGECKO_MARKETS_URL,
            {
                "vs_currency": currency,
                "order": "market_cap_desc",
                "per_page": str(limit),
                "page": str(page),
                "sparkline": "false",
                "price_change_percentage": "24h",
            },
        )
    except HTTPError as exc:
        if exc.code == 429:
            stale = _cache_get_stale(cache_key)
            if stale is not None:
                return stale
        raise

    parsed = data if isinstance(data, list) else []
    if parsed:
        _cache_set(cache_key, parsed)
    return parsed


def _fetch_ranked_markets(currency: str, pages: int, per_page: int) -> list[dict]:
    cache_key = f"markets_ranked:{currency}:{pages}:{per_page}"
    fresh = _cache_get_fresh(cache_key, 180)
    if fresh is not None:
        return fresh

    all_markets: list[dict] = []
    for page in range(1, pages + 1):
        page_data = _fetch_market_list(currency=currency, limit=per_page, page=page)
        if not page_data:
            break
        all_markets.extend(page_data)
        if len(page_data) < per_page:
            break

    dedup: dict[str, dict] = {}
    for item in all_markets:
        if not isinstance(item, dict):
            continue
        coin_id = str(item.get("id") or "").strip()
        if not coin_id:
            continue
        if coin_id in dedup:
            continue
        dedup[coin_id] = item

    ranked = list(dedup.values())
    ranked.sort(key=lambda x: (x.get("market_cap_rank") if isinstance(x.get("market_cap_rank"), int) else 10**9))
    if ranked:
        _cache_set(cache_key, ranked)
    return ranked


def _fetch_coins_directory() -> list[dict]:
    cache_key = "coins:directory"
    fresh = _cache_get_fresh(cache_key, 6 * 60 * 60)
    if fresh is not None:
        return fresh

    try:
        data = _request_json(
            COINGECKO_COINS_LIST_URL,
            {
                "include_platform": "false",
            },
        )
    except HTTPError as exc:
        if exc.code == 429:
            stale = _cache_get_stale(cache_key)
            if stale is not None:
                return stale
        raise

    if not isinstance(data, list):
        return []

    parsed = []
    for item in data:
        if not isinstance(item, dict):
            continue
        parsed.append(
            {
                "id": item.get("id"),
                "symbol": item.get("symbol"),
                "name": item.get("name"),
            }
        )
    if parsed:
        _cache_set(cache_key, parsed)
    return parsed


def _fetch_price_series(coin: str, currency: str, days: str) -> list[float]:
    cache_key = f"series:{coin}:{currency}:{days}"
    fresh = _cache_get_fresh(cache_key, 90)
    if fresh is not None:
        return fresh

    try:
        data = _request_json(
            COINGECKO_MARKET_CHART_URL.format(coin=coin),
            {
                "vs_currency": currency,
                "days": days,
            },
        )
    except HTTPError as exc:
        if exc.code == 429:
            stale = _cache_get_stale(cache_key)
            if stale is not None:
                return stale
        raise

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
    if parsed:
        _cache_set(cache_key, parsed)
    return parsed


def _fetch_ohlc(coin: str, currency: str, days: str) -> list[dict]:
    cache_key = f"ohlc:{coin}:{currency}:{days}"
    fresh = _cache_get_fresh(cache_key, 120)
    if fresh is not None:
        return fresh

    try:
        data = _request_json(
            COINGECKO_OHLC_URL.format(coin=coin),
            {
                "vs_currency": currency,
                "days": days,
            },
        )
    except HTTPError as exc:
        if exc.code == 429:
            stale = _cache_get_stale(cache_key)
            if stale is not None:
                return stale
        raise

    if not isinstance(data, list):
        return []

    candles = []
    for row in data:
        if not isinstance(row, list) or len(row) != 5:
            continue
        timestamp = int(_safe_float(row[0], 0.0))
        candles.append(
            {
                "time": timestamp // 1000,
                "open": _safe_float(row[1], 0.0),
                "high": _safe_float(row[2], 0.0),
                "low": _safe_float(row[3], 0.0),
                "close": _safe_float(row[4], 0.0),
            }
        )
    if candles:
        _cache_set(cache_key, candles)
    return candles


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
            "open_futures_positions": list(demo_account["futures_positions"]),
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
    fee_usd = amount_usd * SPOT_FEE_RATE

    with state_lock:
        current_balance = demo_account["balance_usd"]
        holdings = demo_account["spot_holdings"]
        coin_quantity = _safe_float(holdings.get(coin), 0.0)

        if side == "buy":
            total_cost = amount_usd + fee_usd
            if total_cost > current_balance:
                raise ValueError("Demo balance kam hai.")
            demo_account["balance_usd"] = current_balance - total_cost
            holdings[coin] = round(coin_quantity + quantity, 8)
        else:
            if quantity > coin_quantity:
                raise ValueError(f"{coin} holdings kam hain, pehle buy karein.")
            new_quantity = coin_quantity - quantity
            if new_quantity <= 0:
                holdings.pop(coin, None)
            else:
                holdings[coin] = round(new_quantity, 8)
            demo_account["balance_usd"] = current_balance + amount_usd - fee_usd

        trade = {
            "timestamp": _now_iso(),
            "trade_type": "manual_spot",
            "coin": coin,
            "side": side,
            "amount_usd": round(amount_usd, 2),
            "price": round(price, 6),
            "quantity": round(quantity, 8),
            "fee_usd": round(fee_usd, 4),
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
    fee = notional * FUTURES_FEE_RATE_OPEN

    with state_lock:
        total_required = amount_usd + fee
        if total_required > demo_account["balance_usd"]:
            raise ValueError("Demo balance margin + fee ke liye kaafi nahi.")

        position_id = int(demo_account["next_position_id"])
        demo_account["next_position_id"] = position_id + 1
        demo_account["balance_usd"] -= total_required

        position = {
            "position_id": position_id,
            "opened_at": _now_iso(),
            "coin": coin,
            "side": side,
            "margin_usd": round(amount_usd, 2),
            "leverage": leverage,
            "notional_usd": round(notional, 2),
            "entry_price": round(price, 6),
            "open_fee_usd": round(fee, 4),
            "status": "open",
        }
        demo_account["futures_positions"].append(position)

        trade = {
            "timestamp": _now_iso(),
            "trade_type": "manual_futures_open",
            "coin": coin,
            "side": side,
            "amount_usd": round(amount_usd, 2),
            "leverage": leverage,
            "notional_usd": round(notional, 2),
            "entry_price": round(price, 6),
            "fee_usd": round(fee, 4),
            "position_id": position_id,
            "status": "open",
        }
        _append_trade(trade)

        return {
            "trade": trade,
            "position": position,
            "balance_usd": round(demo_account["balance_usd"], 2),
        }


def _compute_position_live(position: dict, current_price: float) -> dict:
    entry = _safe_float(position.get("entry_price"), 0.0)
    leverage = _safe_float(position.get("leverage"), 1.0)
    margin = _safe_float(position.get("margin_usd"), 0.0)
    side = str(position.get("side", "buy"))
    direction = 1 if side == "buy" else -1

    if entry <= 0 or current_price <= 0 or margin <= 0:
        return {
            **position,
            "current_price": current_price,
            "pnl_pct": 0.0,
            "pnl_usd": 0.0,
        }

    move_pct = ((current_price - entry) / entry) * 100.0
    pnl_pct = move_pct * direction * leverage
    pnl_usd = margin * (pnl_pct / 100.0)
    return {
        **position,
        "current_price": round(current_price, 6),
        "pnl_pct": round(pnl_pct, 4),
        "pnl_usd": round(pnl_usd, 4),
    }


def _live_futures_positions(currency: str) -> list[dict]:
    with state_lock:
        positions = list(demo_account["futures_positions"])

    if not positions:
        return []

    prices_by_coin: dict[str, float] = {}
    for position in positions:
        coin = str(position.get("coin", "")).strip().lower()
        if not coin or coin in prices_by_coin:
            continue
        try:
            market = _fetch_coin_data(coin=coin, currency=currency)
            prices_by_coin[coin] = _safe_float(market.get(currency), 0.0)
        except Exception:  # noqa: BLE001
            prices_by_coin[coin] = 0.0

    live = []
    for position in positions:
        coin = str(position.get("coin", "")).strip().lower()
        live.append(_compute_position_live(position, prices_by_coin.get(coin, 0.0)))
    return live


def _close_futures_position(position_id: int, currency: str = "usd") -> dict:
    with state_lock:
        target = None
        for position in demo_account["futures_positions"]:
            if int(position.get("position_id", -1)) == position_id:
                target = dict(position)
                break
        if target is None:
            raise ValueError("Position nahi mili.")

    coin = str(target.get("coin", "")).strip().lower()
    market = _fetch_coin_data(coin=coin, currency=currency)
    current_price = _safe_float(market.get(currency), 0.0)
    if current_price <= 0:
        raise ValueError("Close price fetch nahi ho saki.")

    live_position = _compute_position_live(target, current_price)
    margin = _safe_float(live_position.get("margin_usd"), 0.0)
    pnl_usd = _safe_float(live_position.get("pnl_usd"), 0.0)
    close_fee = _safe_float(live_position.get("notional_usd"), 0.0) * FUTURES_FEE_RATE_CLOSE

    with state_lock:
        target_index = -1
        for index, position in enumerate(demo_account["futures_positions"]):
            if int(position.get("position_id", -1)) == position_id:
                target_index = index
                break
        if target_index == -1:
            raise ValueError("Position already closed.")
        demo_account["futures_positions"].pop(target_index)
        demo_account["balance_usd"] += margin + pnl_usd - close_fee

        close_trade = {
            "timestamp": _now_iso(),
            "trade_type": "manual_futures_close",
            "position_id": int(target.get("position_id")),
            "coin": target.get("coin"),
            "side": target.get("side"),
            "entry_price": target.get("entry_price"),
            "exit_price": round(current_price, 6),
            "margin_usd": round(margin, 2),
            "leverage": target.get("leverage"),
            "pnl_usd": round(pnl_usd, 4),
            "pnl_pct": live_position.get("pnl_pct"),
            "fee_usd": round(close_fee, 4),
            "status": "closed",
        }
        _append_trade(close_trade)

        return {
            "closed_trade": close_trade,
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
    notional_usd = _safe_float(position.get("notional_usd"), amount_usd * leverage)
    open_fee_usd = _safe_float(position.get("open_fee_usd"), 0.0)
    if entry_price <= 0 or amount_usd <= 0:
        bot_state["open_position"] = None
        return None

    price_move_pct = ((close_price - entry_price) / entry_price) * 100.0
    pnl_pct = price_move_pct * direction * leverage
    pnl_usd = amount_usd * (pnl_pct / 100.0)
    close_fee_usd = notional_usd * BOT_FEE_RATE_CLOSE
    demo_account["balance_usd"] += amount_usd + pnl_usd - close_fee_usd

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
        "open_fee_usd": round(open_fee_usd, 4),
        "close_fee_usd": round(close_fee_usd, 4),
        "total_fees_usd": round(open_fee_usd + close_fee_usd, 4),
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
                    leverage = _safe_float(settings.get("leverage"), 1.0)
                    notional = amount * leverage
                    open_fee = notional * BOT_FEE_RATE_OPEN
                    total_required = amount + open_fee

                    if total_required > demo_account["balance_usd"]:
                        bot_state["last_error"] = "Bot trade ke liye demo balance kam hai."
                    elif amount > 0 and current_price > 0:
                        demo_account["balance_usd"] -= total_required
                        bot_state["open_position"] = {
                            "opened_at": _now_iso(),
                            "coin": coin,
                            "side": signal,
                            "entry_price": round(current_price, 6),
                            "amount_usd": amount,
                            "leverage": leverage,
                            "notional_usd": round(notional, 2),
                            "open_fee_usd": round(open_fee, 4),
                        }
                        _append_trade(
                            {
                                "timestamp": _now_iso(),
                                "trade_type": "bot_open",
                                "coin": coin,
                                "side": signal,
                                "entry_price": round(current_price, 6),
                                "amount_usd": round(amount, 2),
                                "leverage": leverage,
                                "notional_usd": round(notional, 2),
                                "fee_usd": round(open_fee, 4),
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
        coin_options=COIN_OPTIONS,
    )


@app.route("/trading/futures")
def trading_futures():
    return render_template(
        "futures.html",
        page_name="trading",
        default_coin=DEFAULT_COIN,
        default_currency=DEFAULT_CURRENCY,
        coin_options=COIN_OPTIONS,
    )


@app.route("/trading/bot")
def trading_bot():
    return render_template(
        "bot.html",
        page_name="trading",
        default_coin=DEFAULT_COIN,
        default_currency=DEFAULT_CURRENCY,
        coin_options=COIN_OPTIONS,
    )


@app.route("/chart")
def chart_page():
    return render_template(
        "chart.html",
        page_name="chart",
        default_coin=DEFAULT_COIN,
        default_currency=DEFAULT_CURRENCY,
        coin_options=COIN_OPTIONS,
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
        if exc.code == 429:
            return jsonify({"error": "Market API rate limit hit. Thori dair baad retry karein."}), 429
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
        page = int(request.args.get("page", "1"))
    except ValueError:
        return jsonify({"error": "Invalid query params."}), 400

    limit = max(5, min(limit, 250))
    page = max(1, page)

    try:
        raw_markets = _fetch_market_list(currency=currency, limit=limit, page=page)
    except HTTPError as exc:
        if exc.code == 429:
            return jsonify({"error": "Market API rate limit hit. Thori dair baad retry karein."}), 429
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
                "market_cap_rank": item.get("market_cap_rank"),
                "market_cap": item.get("market_cap"),
                "total_volume": item.get("total_volume"),
                "price_change_percentage_24h": item.get("price_change_percentage_24h"),
            }
        )

    return jsonify(
        {
            "currency": currency,
            "page": page,
            "count": len(markets),
            "fetched_at": _now_iso(),
            "markets": markets,
        }
    )


@app.route("/api/coins", methods=["GET"])
def api_coins():
    try:
        coins = _fetch_coins_directory()
    except HTTPError as exc:
        if exc.code == 429:
            return jsonify({"error": "Market API rate limit hit. Thori dair baad retry karein."}), 429
        return jsonify({"error": "Market provider error", "details": f"HTTP {exc.code}"}), 502
    except URLError:
        return jsonify({"error": "Provider se connection nahi ho saka."}), 503
    except json.JSONDecodeError:
        return jsonify({"error": "Provider ne invalid response diya."}), 502

    return jsonify(
        {
            "count": len(coins),
            "coins": coins,
            "fetched_at": _now_iso(),
        }
    )


@app.route("/api/markets/ranked", methods=["GET"])
def api_markets_ranked():
    try:
        currency = _normalize_currency(request.args.get("currency"))
        pages = int(request.args.get("pages", "4"))
        per_page = int(request.args.get("per_page", "250"))
    except ValueError:
        return jsonify({"error": "Invalid query params."}), 400

    pages = max(1, min(pages, 8))
    per_page = max(50, min(per_page, 250))

    try:
        raw_markets = _fetch_ranked_markets(currency=currency, pages=pages, per_page=per_page)
    except HTTPError as exc:
        if exc.code == 429:
            return jsonify({"error": "Market API rate limit hit. Thori dair baad retry karein."}), 429
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
                "market_cap_rank": item.get("market_cap_rank"),
                "current_price": item.get("current_price"),
                "market_cap": item.get("market_cap"),
                "total_volume": item.get("total_volume"),
                "price_change_percentage_24h": item.get("price_change_percentage_24h"),
            }
        )

    return jsonify(
        {
            "currency": currency,
            "pages": pages,
            "per_page": per_page,
            "count": len(markets),
            "fetched_at": _now_iso(),
            "markets": markets,
        }
    )


@app.route("/api/ohlc", methods=["GET"])
def api_ohlc():
    try:
        coin = _normalize_coin_id(request.args.get("coin"))
        currency = _normalize_currency(request.args.get("currency"))
        days = str(request.args.get("days", "1")).strip()
        if days not in {"1", "7", "30", "90"}:
            raise ValueError("days sirf 1, 7, 30, 90 ho sakta hai.")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        candles = _fetch_ohlc(coin=coin, currency=currency, days=days)
    except HTTPError as exc:
        if exc.code == 429:
            return jsonify({"error": "Market API rate limit hit. Thori dair baad retry karein."}), 429
        return jsonify({"error": "Market provider error", "details": f"HTTP {exc.code}"}), 502
    except URLError:
        return jsonify({"error": "Provider se connection nahi ho saka."}), 503
    except json.JSONDecodeError:
        return jsonify({"error": "Provider ne invalid response diya."}), 502

    return jsonify(
        {
            "coin": coin,
            "currency": currency,
            "days": days,
            "count": len(candles),
            "candles": candles,
            "fetched_at": _now_iso(),
        }
    )


@app.route("/api/trade/status", methods=["GET"])
def api_trade_status():
    currency = "usd"
    with state_lock:
        running_bot = bool(bot_state["running"])
        open_bot = dict(bot_state["open_position"]) if bot_state["open_position"] else None

    live_futures = _live_futures_positions(currency=currency)
    total_futures_pnl = sum(_safe_float(item.get("pnl_usd"), 0.0) for item in live_futures)

    bot_live = None
    if open_bot:
        coin = str(open_bot.get("coin", "")).strip().lower()
        try:
            market = _fetch_coin_data(coin=coin, currency=currency)
            current_price = _safe_float(market.get(currency), 0.0)
            if current_price > 0:
                side = str(open_bot.get("side", "buy"))
                entry_price = _safe_float(open_bot.get("entry_price"), 0.0)
                leverage = _safe_float(open_bot.get("leverage"), 1.0)
                amount_usd = _safe_float(open_bot.get("amount_usd"), 0.0)
                direction = 1 if side == "buy" else -1
                if entry_price > 0 and amount_usd > 0:
                    move_pct = ((current_price - entry_price) / entry_price) * 100.0
                    pnl_pct = move_pct * direction * leverage
                    pnl_usd = amount_usd * (pnl_pct / 100.0)
                    bot_live = {
                        **open_bot,
                        "current_price": round(current_price, 6),
                        "pnl_pct": round(pnl_pct, 4),
                        "pnl_usd": round(pnl_usd, 4),
                    }
        except Exception:  # noqa: BLE001
            bot_live = {**open_bot, "current_price": None, "pnl_pct": None, "pnl_usd": None}

    with state_lock:
        return jsonify(
            {
                "balance_usd": round(demo_account["balance_usd"], 2),
                "futures_open_count": len(demo_account["futures_positions"]),
                "futures_positions": live_futures,
                "futures_total_pnl_usd": round(total_futures_pnl, 4),
                "bot_running": running_bot,
                "bot_open_position": bot_live,
                "updated_at": _now_iso(),
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
        if exc.code == 429:
            return jsonify({"error": "Market API rate limit hit. Thori dair baad retry karein."}), 429
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


@app.route("/api/trade/close", methods=["POST"])
def api_trade_close():
    payload = request.get_json(silent=True) or {}
    try:
        position_id = int(payload.get("position_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "position_id required hai."}), 400

    try:
        result = _close_futures_position(position_id=position_id, currency="usd")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except HTTPError as exc:
        if exc.code == 429:
            return jsonify({"error": "Market API rate limit hit. Thori dair baad retry karein."}), 429
        return jsonify({"error": "Market provider error", "details": f"HTTP {exc.code}"}), 502
    except URLError:
        return jsonify({"error": "Provider se connection nahi ho saka."}), 503
    except json.JSONDecodeError:
        return jsonify({"error": "Provider ne invalid response diya."}), 502

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
        required = amount_usd + (amount_usd * leverage * BOT_FEE_RATE_OPEN)
        if required > demo_account["balance_usd"]:
            return jsonify({"error": "Demo balance bot amount + opening fee se kam hai."}), 400

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
        open_position = dict(bot_state["open_position"]) if bot_state["open_position"] else None

    live_open_position = None
    if open_position:
        coin = str(open_position.get("coin", "")).strip().lower()
        try:
            market = _fetch_coin_data(coin=coin, currency="usd")
            current_price = _safe_float(market.get("usd"), 0.0)
            side = str(open_position.get("side", "buy"))
            entry = _safe_float(open_position.get("entry_price"), 0.0)
            leverage = _safe_float(open_position.get("leverage"), 1.0)
            amount = _safe_float(open_position.get("amount_usd"), 0.0)
            direction = 1 if side == "buy" else -1
            if current_price > 0 and entry > 0 and amount > 0:
                move_pct = ((current_price - entry) / entry) * 100.0
                pnl_pct = move_pct * direction * leverage
                pnl_usd = amount * (pnl_pct / 100.0)
                live_open_position = {
                    **open_position,
                    "current_price": round(current_price, 6),
                    "pnl_pct": round(pnl_pct, 4),
                    "pnl_usd": round(pnl_usd, 4),
                }
            else:
                live_open_position = {**open_position, "current_price": None, "pnl_pct": None, "pnl_usd": None}
        except Exception:  # noqa: BLE001
            live_open_position = {**open_position, "current_price": None, "pnl_pct": None, "pnl_usd": None}

    with state_lock:
        return jsonify(
            {
                "running": bot_state["running"],
                "settings": dict(bot_state["settings"]),
                "last_signal": bot_state["last_signal"],
                "last_price": bot_state["last_price"],
                "last_error": bot_state["last_error"],
                "last_check_at": bot_state["last_check_at"],
                "open_position": live_open_position,
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
        if exc.code == 429:
            return jsonify({"error": "Market API rate limit hit. Thori dair baad retry karein."}), 429
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
