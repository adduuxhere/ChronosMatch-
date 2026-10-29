import math
import os
import sqlite3
import threading 
from flask import Flask, jsonify, request
from database import DB_PATH, close_db, get_db, init_db
from engine import MatchingEngine
 
OPEN_STATUSES = ("PENDING", "PARTIAL")
app = Flask(__name__)
app.teardown_appcontext(close_db)
@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    return resp
engine_lock = threading.Lock()
engine = MatchingEngine()
def rebuild_engine():
    global engine
    new_engine = MatchingEngine()
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute(
            """SELECT id, symbol, user_id, side, price, remaining_qty
               FROM orders
               WHERE status IN ('PENDING', 'PARTIAL')
               ORDER BY id"""
        ).fetchall()
    finally:
        db.close()
 
    for r in rows:
        new_engine.restore({
            "id": r["id"],
            "symbol": r["symbol"],
            "user_id": r["user_id"],
            "side": r["side"],
            "price": r["price"],
            "quantity": r["remaining_qty"],
        })
    engine = new_engine
init_db()
rebuild_engine()
 
def parse_int(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise ValueError(f"{name} must be a whole number")
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            raise ValueError(f"{name} must be an integer")
    raise ValueError(f"{name} must be an integer")
 
 
def parse_price(value):
    if isinstance(value, bool):
        raise ValueError("price must be a number")
    try:
        price = float(value)
    except (TypeError, ValueError):
        raise ValueError("price must be a number")
    if not math.isfinite(price):
        raise ValueError("price must be a finite number")
    return price
@app.route("/")
def home():
    return jsonify({
        "project": "ChronosMatch",
        "status": "running",
        "message": "Home API working",
    })
@app.route("/orders", methods=["GET"])
def get_orders():
    symbol = request.args.get("symbol")
    status = request.args.get("status")
    user_id = request.args.get("user_id")
    try:
        limit = min(max(int(request.args.get("limit", 100)), 1), 500)
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400
 
    query = "SELECT * FROM orders WHERE 1=1"
    params = []
    if symbol:
        query += " AND symbol = ?"
        params.append(symbol.upper())
    if status:
        query += " AND status = ?"
        params.append(status.upper())
    if user_id:
        try:
            params.append(int(user_id))
        except ValueError:
            return jsonify({"error": "user_id must be an integer"}), 400
        query += " AND user_id = ?"
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
 
    rows = get_db().execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])
 
 
@app.route("/orders/<int:order_id>", methods=["GET"])
def get_order(order_id):
    db = get_db()
    row = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        return jsonify({"error": "Order not found"}), 404
 
    trades = db.execute(
        """SELECT * FROM trades
           WHERE buy_order_id = ? OR sell_order_id = ?
           ORDER BY id""",
        (order_id, order_id),
    ).fetchall()
 
    result = dict(row)
    result["trades"] = [dict(t) for t in trades]
    return jsonify(result)
@app.route("/orders", methods=["POST"])
def create_order():
    data = request.get_json(silent=True) or {}
    required = ["symbol", "user_id", "side", "price", "quantity"]
    missing = [key for key in required if key not in data]
    if missing:
        return jsonify({
            "error": "Missing required fields",
            "missing": missing,
        }), 400
    side = str(data["side"]).strip().upper()
    if side not in ("BUY", "SELL"):
        return jsonify({"error": "side must be BUY or SELL"}), 400 
    symbol = str(data["symbol"]).strip().upper()
    if not symbol:
        return jsonify({"error": "symbol must not be empty"}), 400
    try:
        price = parse_price(data["price"])
        quantity = parse_int(data["quantity"], "quantity")
        user_id = parse_int(data["user_id"], "user_id")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
 
    if price <= 0 or quantity <= 0:
        return jsonify({"error": "price and quantity must be positive"}), 400
 
    db = get_db()
    failed = False
 
    with engine_lock:
        try:
            with db:
                cursor = db.execute(
                    """INSERT INTO orders
                       (symbol, user_id, side, price, quantity, remaining_qty)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (symbol, user_id, side, price, quantity, quantity),
                )
                order_id = cursor.lastrowid
 
                trades = engine.add_order({
                    "id": order_id,
                    "symbol": symbol,
                    "user_id": user_id,
                    "side": side.lower(),
                    "price": price,
                    "quantity": quantity,
                })
 
                for t in trades:
                    db.execute(
                        """INSERT INTO trades
                           (symbol, buy_order_id, sell_order_id, price, quantity)
                           VALUES (?, ?, ?, ?, ?)""",
                        (symbol, t["buy_order_id"], t["sell_order_id"],
                         t["price"], t["quantity"]),
                    )
                    for oid in (t["buy_order_id"], t["sell_order_id"]):
                        db.execute(
                            """UPDATE orders
                               SET remaining_qty = remaining_qty - ?,
                                   status = CASE
                                       WHEN remaining_qty - ? = 0 THEN 'FILLED'
                                       ELSE 'PARTIAL'
                                   END
                               WHERE id = ?""",
                            (t["quantity"], t["quantity"], oid),
                        )
        except Exception:
            app.logger.exception("Order creation failed")
            failed = True
            rebuild_engine()
 
    if failed:
        return jsonify({"error": "Internal error"}), 500
 
    row = db.execute(
        "SELECT status, remaining_qty FROM orders WHERE id = ?", (order_id,)
    ).fetchone()
 
    return jsonify({
        "message": "Order created successfully",
        "order_id": order_id,
        "status": row["status"],
        "remaining_qty": row["remaining_qty"],
        "trades": trades,
    }), 201
 
 
@app.route("/orders/<int:order_id>", methods=["DELETE"])
def cancel_order(order_id):
    db = get_db()
 
    with engine_lock:
        try:
            with db:
                row = db.execute(
                    "SELECT status FROM orders WHERE id = ?", (order_id,)
                ).fetchone()
                if row is None:
                    return jsonify({"error": "Order not found"}), 404
                if row["status"] not in OPEN_STATUSES:
                    return jsonify({
                        "error": f"Order is {row['status']} and cannot be cancelled"
                    }), 409
 
                db.execute(
                    "UPDATE orders SET status = 'CANCELLED' WHERE id = ?",
                    (order_id,),
                )
            engine.cancel_order(order_id)
        except Exception:
            app.logger.exception("Order cancel failed")
            rebuild_engine()
            return jsonify({"error": "Internal error"}), 500
 
    return jsonify({"message": "Order cancelled", "order_id": order_id})
 
 
@app.route("/trades", methods=["GET"])
def get_trades():
    symbol = request.args.get("symbol")
    try:
        limit = min(max(int(request.args.get("limit", 100)), 1), 500)
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400
 
    query = "SELECT * FROM trades"
    params = []
    if symbol:
        query += " WHERE symbol = ?"
        params.append(symbol.upper())
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
 
    rows = get_db().execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])
 
 
@app.route("/book/<symbol>", methods=["GET"])
def get_book(symbol):
    symbol = symbol.upper()
    db = get_db()
 
    def levels(side, order):
        rows = db.execute(
            f"""SELECT price, SUM(remaining_qty) AS quantity
                FROM orders
                WHERE symbol = ? AND side = ?
                  AND status IN ('PENDING', 'PARTIAL')
                GROUP BY price
                ORDER BY price {order}""",
            (symbol, side),
        ).fetchall()
        return [{"price": r["price"], "quantity": r["quantity"]} for r in rows]
 
    return jsonify({
        "symbol": symbol,
        "bids": levels("BUY", "DESC"),  
        "asks": levels("SELL", "ASC"),  
    })
 
@app.errorhandler(404)
def not_found(_e):
    return jsonify({"error": "Not found"}), 404
 
 
@app.errorhandler(405)
def method_not_allowed(_e):
    return jsonify({"error": "Method not allowed"}), 405
 
 
if __name__ == "__main__":
    app.run(port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")