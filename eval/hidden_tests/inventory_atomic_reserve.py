import pytest
from app.service import InventoryService, OutOfStockError
from app.store import Inventory


def test_invalid_quantity_does_not_mutate():
    inventory = Inventory({"sku": 3})
    service = InventoryService(inventory)
    with pytest.raises(ValueError):
        service.reserve("sku", 0)
    assert inventory.get("sku") == 3


def test_exact_stock_reaches_zero():
    inventory = Inventory({"sku": 3})
    service = InventoryService(inventory)
    assert service.reserve("sku", 3) == 0
    assert inventory.get("sku") == 0


def test_unknown_sku_is_out_of_stock_without_mutation():
    inventory = Inventory({})
    service = InventoryService(inventory)
    with pytest.raises(OutOfStockError):
        service.reserve("missing", 1)
    assert inventory.get("missing") == 0
