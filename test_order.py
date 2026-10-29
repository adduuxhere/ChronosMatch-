import json
import urllib.request
import urllib.error

def post(payload):
    req = urllib.request.Request(
        "http://127.0.0.1:5000/orders",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            print(r.status, r.read().decode())
    except urllib.error.HTTPError as e:
        print(e.code, e.read().decode())

post({"symbol": "AAPL", "user_id": 1, "side": "SELL", "price": 100, "quantity": 10})
post({"symbol": "AAPL", "user_id": 2, "side": "BUY", "price": 101, "quantity": 4})