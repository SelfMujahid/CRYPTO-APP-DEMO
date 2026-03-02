from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

user_data = {
    "balance": 10000,
    "trades": []
}

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
