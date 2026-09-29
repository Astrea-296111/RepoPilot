import pytest
from app.service import InventoryService, OutOfStockError
from app.store import Inventory


def test_insufficient_stock_does_not_change_inventory():
    inventory = Inventory({"sku": 2})
    service = InventoryService(inventory)
    with pytest.raises(OutOfStockError):
        service.reserve("sku", 3)
    assert inventory.get("sku") == 2
