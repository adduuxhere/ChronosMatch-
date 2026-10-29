import os
import sqlite3
import flask 
DB_PATH = os.environ.get("CHRONOS_DB", "chronosmatch.db")
def get_db():
    if "db" not in flask.g:
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        flask.g.db = db
    return flask.g.db
def close_db(_exc=None):
    db = flask.g.pop("db", None)
    if db is not None:
        db.close() 
def init_db():
    db = sqlite3.connect(DB_PATH)
    try:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol        TEXT    NOT NULL,
                user_id       INTEGER NOT NULL,
                side          TEXT    NOT NULL CHECK (side IN ('BUY','SELL')),
                price         REAL    NOT NULL CHECK (price > 0),
                quantity      INTEGER NOT NULL CHECK (quantity > 0),
                remaining_qty INTEGER NOT NULL,
                status        TEXT    NOT NULL DEFAULT 'PENDING'
                              CHECK (status IN ('PENDING','PARTIAL','FILLED','CANCELLED')),
                created_at    REAL    NOT NULL DEFAULT (strftime('%s','now')),
                CHECK (remaining_qty >= 0 AND remaining_qty <= quantity)
            );
 
            CREATE TABLE IF NOT EXISTS trades (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol        TEXT    NOT NULL,
                buy_order_id  INTEGER NOT NULL REFERENCES orders(id),
                sell_order_id INTEGER NOT NULL REFERENCES orders(id),
                price         REAL    NOT NULL CHECK (price > 0),
                quantity      INTEGER NOT NULL CHECK (quantity > 0),
                executed_at   REAL    NOT NULL DEFAULT (strftime('%s','now'))
            );
 
            CREATE INDEX IF NOT EXISTS idx_orders_book
                ON orders (symbol, side, status, price, created_at);
            CREATE INDEX IF NOT EXISTS idx_trades_buy  ON trades (buy_order_id);
            CREATE INDEX IF NOT EXISTS idx_trades_sell ON trades (sell_order_id);
        """)
        db.commit()
    finally:
        db.close()
 