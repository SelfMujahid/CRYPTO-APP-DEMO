# CRYPTO-APP-DEMO

Flask based crypto dashboard with multi-page flow:
- `Home (/)` => all crypto market list
- `Real-Time BTC (/btc)` => intentionally blank page
- `Trading (/trading)` => demo amount + Spot/Futures/Bot modules
- `Chart (/chart)` => candlestick chart page
- Spot page => `/trading/spot`
- Futures page => `/trading/futures`
- Bot page => `/trading/bot`

APIs:
- `/api/account`
- `/api/market?coin=bitcoin&currency=usd`
- `/api/markets?currency=usd&limit=250`
- `/api/markets/ranked?currency=usd&pages=4&per_page=250`
- `/api/coins` (all coins directory)
- `/api/ohlc?coin=bitcoin&currency=usd&days=1`
- `/api/trade/execute` (spot/futures demo)
- `/api/trade/status` (live running trade P/L)
- `/api/trade/close` (manual close futures position)
- `/api/bot/start`, `/api/bot/stop`, `/api/bot/status`

Fees (exchange-style demo):
- Spot: 0.10% per trade side
- Futures: 0.06% open + 0.06% close
- Bot: 0.06% open + 0.06% close

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open: `http://127.0.0.1:5000`

## APK Build (Low-Spec Laptop Friendly)

APK local Android Studio ke baghair bhi ban sakta hai via GitHub Actions.

1. App ko pehle online host karo (Render/Railway/VPS), taake URL mile, e.g. `https://your-domain.com`
2. GitHub repo me jao: `Actions` tab
3. Workflow select karo: `Build Android APK`
4. `Run workflow` press karo aur `app_url` me hosted URL do
5. Build complete hone par artifact `crypto-app-debug-apk` download karo

Android wrapper project path: `android-webview-app/`
