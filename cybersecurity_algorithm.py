def detect_grid_anomaly(load, generation, prev_load, grid_status, defenses):

    risk = 0
    detection = "Normal Operation"
    recommendation = "Monitoring System"

    # ---------------------------------
    # Feature Extraction
    # ---------------------------------
    load_change = load - prev_load
    load_ratio = load / generation if generation > 0 else 0

    # ---------------------------------
    # Rule 1: Load Injection Attack
    # ---------------------------------
    if load_change > 80:
        risk += 35
        detection = "Load Injection Attack"
        recommendation = "Investigate abnormal load spike"

    # ---------------------------------
    # Rule 2: Grid Overload
    # ---------------------------------
    if generation > 0 and load_ratio > 1.1:
        risk += 40
        detection = "Grid Overload Detected"
        recommendation = "Reduce load immediately"

    # ---------------------------------
    # Rule 3: Instability Attack
    # ---------------------------------
    if grid_status == "INSTABILITY":
        risk += 40
        detection = "Grid Instability Attack"
        recommendation = "Stabilize power generation"

    # ---------------------------------
    # Rule 4: Grid Offline Attack
    # ---------------------------------
    if grid_status == "OFFLINE":
        risk += 50
        detection = "Grid Offline Attack"
        recommendation = "Check grid connectivity"

    # ---------------------------------
    # Rule 5: Defense Weakness
    # ---------------------------------
    if not defenses.get("authGateway", False):
        risk += 10

    if not defenses.get("firewall", False):
        risk += 10

    if not defenses.get("anomalyDetection", False):
        risk += 5

    # ---------------------------------
    # Rule 6: Coordinated Attack Detection
    # ---------------------------------
    if load_change > 50 and grid_status == "INSTABILITY":
        risk += 25
        detection = "Coordinated Grid Attack"
        recommendation = "Activate all defenses immediately"

    # ---------------------------------
    # Rule 7: Stealthy Load Manipulation
    # ---------------------------------
    if 20 < load_change < 50:
        risk += 15
        detection = "Suspicious Load Manipulation"
        recommendation = "Monitor meter integrity"

    # ---------------------------------
    # Rule 8: Defense Bypass Attempt
    # ---------------------------------
    if risk > 40 and (
        not defenses.get("authGateway", False) or
        not defenses.get("firewall", False)
    ):
        risk += 20
        detection = "Defense Bypass Attempt"
        recommendation = "Enable security defenses immediately"

    # ---------------------------------
    # Risk Normalization
    # ---------------------------------
    risk = min(risk, 100)

    return risk, detection, recommendation