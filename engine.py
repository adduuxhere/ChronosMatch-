import heapq
class MatchingEngine:
    def __init__(self):
        self.books = {}    
        self.orders = {}   
 
    def _book(self, symbol):
        return self.books.setdefault(symbol, {"buy": [], "sell": []})
 
    @staticmethod
    def _key(side, price, order_id):
        return (-price if side == "buy" else price, order_id)
    def restore(self, order):
        side = order["side"].lower()
        order = {**order, "side": side}
        self.orders[order["id"]] = order
        heapq.heappush(
            self._book(order["symbol"])[side],
            self._key(side, order["price"], order["id"]),
        )
 
    def add_order(self, order):
        side = order["side"].lower()
        if side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
 
        order = {**order, "side": side}
        book = self._book(order["symbol"])
        opposite = book["sell" if side == "buy" else "buy"]
 
        trades = []
        skipped = [] 
 
        while order["quantity"] > 0 and opposite:
            entry = opposite[0]
            resting = self.orders.get(entry[1])
 
            if resting is None:             
                heapq.heappop(opposite)
                continue
 
            if side == "buy":
                crosses = resting["price"] <= order["price"]
            else:
                crosses = resting["price"] >= order["price"]
            if not crosses:
                break 
            if resting["user_id"] == order["user_id"]:  
                skipped.append(heapq.heappop(opposite))
                continue
            qty = min(order["quantity"], resting["quantity"])
            order["quantity"] -= qty
            resting["quantity"] -= qty
            buy_id, sell_id = (
                (order["id"], resting["id"]) if side == "buy"
                else (resting["id"], order["id"])
            )
            trades.append({
                "symbol": order["symbol"],
                "buy_order_id": buy_id,
                "sell_order_id": sell_id,
                "price": resting["price"],
                "quantity": qty,
            })
 
            if resting["quantity"] == 0:
                heapq.heappop(opposite)
                del self.orders[resting["id"]]
 
        for entry in skipped:
            heapq.heappush(opposite, entry)
 
        if order["quantity"] > 0:
            self.orders[order["id"]] = order
            heapq.heappush(
                book[side], self._key(side, order["price"], order["id"])
            )
 
        return trades
 
    def cancel_order(self, order_id):
        return self.orders.pop(order_id, None) is not None
 