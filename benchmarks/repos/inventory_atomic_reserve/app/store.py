class Inventory:
    def __init__(self, stock: dict[str, int]):
        self.stock = dict(stock)

    def get(self, sku: str) -> int:
        return self.stock.get(sku, 0)

    def decrement(self, sku: str, qty: int) -> None:
        self.stock[sku] = self.get(sku) - qty
