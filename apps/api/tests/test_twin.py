from retailtwin_api.demo_runtime.services.twin import TwinService, SlotState
import pytest

def test_twin_service_basic():
    service = TwinService()
    # Need to populate slots first, as methods like apply_facings require existing slots.
    # I can use load_from_store.
    service.load_from_store([
        {"slot_id": "s1", "sku": "sku1", "facings": 1, "shelf_quantity": 10, "backroom_quantity": 5}
    ])
    
    assert service.read_slot("s1").sku == "sku1"
    
    service.apply_facings("s1", 2)
    assert service.read_slot("s1").facings == 2
    assert service.get_version() == "1"

def test_apply_facings_error():
    service = TwinService()
    with pytest.raises(KeyError, match="does not exist"):
        service.apply_facings("non-existent", 2)

def test_apply_move_error():
    service = TwinService()
    service.load_from_store([
        {"slot_id": "s1", "sku": "sku1", "facings": 1, "shelf_quantity": 10, "backroom_quantity": 5}
    ])
    with pytest.raises(KeyError, match="Slot not found"):
        service.apply_move("s1", "s2", 1)
