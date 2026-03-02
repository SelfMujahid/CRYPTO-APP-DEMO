# CRYPTO-APP-DEMO

Flask based crypto dashboard with multi-page flow:
- `Home (/)` => all crypto market list
- `Real-Time BTC (/btc)` => intentionally blank page
- `Trading (/trading)` => demo amount + Spot/Futures/Bot modules
- Spot page => `/trading/spot`
- Futures page => `/trading/futures`
- Bot page => `/trading/bot`

APIs:
- `/api/account`
- `/api/market?coin=bitcoin&currency=usd`
- `/api/markets?currency=usd&limit=50`
- `/api/trade/execute` (spot/futures demo)
- `/api/bot/start`, `/api/bot/stop`, `/api/bot/status`

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open: `http://127.0.0.1:5000`
