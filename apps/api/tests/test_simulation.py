from retailtwin_api.demo_runtime.services.simulation import SimulationService
from retailtwin_api.demo_runtime.services.twin import TwinService
import pytest

def test_simulation_service():
    twin = TwinService()
    twin.load_from_store([
        {"slot_id": "s1", "sku": "sku1", "facings": 1, "shelf_quantity": 10, "backroom_quantity": 5},
        {"slot_id": "s2", "sku": "sku1", "facings": 1, "shelf_quantity": 10, "backroom_quantity": 5}
    ])
    sim = SimulationService(twin)
    snap = sim.clone()
    
    # Test apply - facings
    sim.apply(snap, [
        {"action_type": "facings", "slot_id": "s1", "facings": 5}
    ])
    assert snap.slots["s1"].facings == 5
    
    # Test apply - replenish
    sim.apply(snap, [
        {"action_type": "replenish", "slot_id": "s2", "quantity": 10}
    ])
    assert snap.slots["s2"].shelf_quantity == 20
    
    # Test apply - move
    sim.apply(snap, [
        {"action_type": "move", "slot_id": "s1", "from_slot_id": "s1", "to_slot_id": "s2", "quantity": 2}
    ])
    assert snap.slots["s1"].shelf_quantity == 8
    assert snap.slots["s2"].shelf_quantity == 22
    
    # Test evaluate
    kpi = sim.evaluate(snap)
    assert kpi.total_shelf_quantity == 30

def test_simulation_apply_missing_slot():
    twin = TwinService()
    sim = SimulationService(twin)
    snap = sim.clone()
    
    results = sim.apply(snap, [
        {"action_type": "facings", "slot_id": "n/a", "facings": 5}
    ])
    assert len(results) == 1
    assert results[0].slot_id == "n/a"
