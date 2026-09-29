from .store import Inventory


class OutOfStockError(RuntimeError):
    pass


class InventoryService:
    def __init__(self, inventory: Inventory):
        self.inventory = inventory

    def reserve(self, sku: str, qty: int) -> int:
        available = self.inventory.get(sku)
        self.inventory.decrement(sku, qty)
        if qty <= 0:
            raise ValueError("qty must be positive")
        if available < qty:
            raise OutOfStockError(sku)
        return available - qty
