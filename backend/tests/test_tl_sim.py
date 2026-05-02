"""Quick test for the traffic light simulation service (isolated import)."""
import time
import json
import importlib.util
import os

# Load the sim module directly without triggering app.services.__init__
module_path = os.path.join(os.path.dirname(__file__), "app", "services", "traffic_light_sim_service.py")
spec = importlib.util.spec_from_file_location("tl_sim", module_path)
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)
get_state = sim.get_state

# Test 1: Get initial state
result = get_state("test_intersection")
print("=== Test 1: Initial state ===")
print(json.dumps(result, indent=2))

# Verify structure
assert result["intersection_id"] == "test_intersection"
for d in ("north", "south", "east", "west"):
    assert d in result["directions"], f"Missing direction: {d}"
assert result["cycle_duration"] == 66

# Verify NS match, WE match, opposite states
ns = result["directions"]["north"]
ss = result["directions"]["south"]
ee = result["directions"]["east"]
ww = result["directions"]["west"]
assert ns["state"] == ss["state"], "N/S must match"
assert ee["state"] == ww["state"], "E/W must match"
if ns["state"] in ("green", "yellow"):
    assert ee["state"] == "red"
if ee["state"] in ("green", "yellow"):
    assert ns["state"] == "red"
print(f"NS: {ns['state']} {ns['remaining']}s | WE: {ee['state']} {ee['remaining']}s")

# Test 2: Countdown after 1s
time.sleep(1)
r2 = get_state("test_intersection")
ns2 = r2["directions"]["north"]
ee2 = r2["directions"]["east"]
print(f"\n=== Test 2: After 1s ===")
print(f"NS: {ns2['state']} {ns2['remaining']}s | WE: {ee2['state']} {ee2['remaining']}s")
if ns["state"] == ns2["state"]:
    diff = ns["remaining"] - ns2["remaining"]
    assert 0 <= diff <= 2, f"Expected ~1s decrease, got {diff}"

print("\n=== ALL TESTS PASSED ===")
