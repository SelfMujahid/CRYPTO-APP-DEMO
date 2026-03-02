# CRYPTO-APP-DEMO

Flask based crypto dashboard with:
- classic trading API routes: `/balance`, `/trade`
- real-time market API route: `/api/market?coin=bitcoin&currency=usd`
- styled dashboard UI on `/` (BTC neon theme + rotating cube + live stats)

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open: `http://127.0.0.1:5000`
