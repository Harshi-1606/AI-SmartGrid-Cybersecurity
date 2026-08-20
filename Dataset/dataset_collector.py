import requests
import csv
import os
import time
from datetime import datetime, timezone


# ============================================================
# CONFIGURATION
# ============================================================

FIREBASE_URL = (
    "https://smartgrid-harshi-default-rtdb."
    "asia-southeast1.firebasedatabase.app/"
)

STATUS_ENDPOINT = FIREBASE_URL + ".json"

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(
    OUTPUT_DIR,
    "smartgrid_dataset.csv"
)

SAMPLE_INTERVAL = 2  # seconds


# ============================================================
# DATA COLLECTION
# ============================================================

previous_load = None


def get_grid_data():
    """Read the current Smart Grid state from Firebase."""

    try:
        response = requests.get(
            STATUS_ENDPOINT,
            timeout=5
        )

        response.raise_for_status()

        data = response.json()

        if data is None:
            return None

        return data

    except requests.RequestException as e:
        print(f"[ERROR] Firebase connection failed: {e}")
        return None

    except Exception as e:
        print(f"[ERROR] Could not read Firebase data: {e}")
        return None


def create_dataset_row(data):
    """Convert Firebase data into one dataset row."""

    global previous_load

    grid = data.get("grid", {})
    devices = data.get("devices", {})

    # --------------------------------------------------------
    # Basic grid measurements
    # --------------------------------------------------------

    total_load = float(grid.get("totalLoad", 0) or 0)
    total_generation = float(
        grid.get("totalGeneration", 0) or 0
    )

    grid_status = grid.get(
        "gridStatus",
        "UNKNOWN"
    )

    grid_power = grid.get(
        "power",
        "UNKNOWN"
    )

    attack = grid.get(
        "attack",
        "NONE"
    )

    shutdown_reason = grid.get(
        "shutdownReason",
        "NONE"
    )

    max_generation = float(
        grid.get("maxGeneration", 0) or 0
    )

    # --------------------------------------------------------
    # Derived features
    # --------------------------------------------------------

    if previous_load is None:
        load_change = 0.0
    else:
        load_change = total_load - previous_load

    if total_generation > 0:
        load_ratio = total_load / total_generation
    else:
        load_ratio = 0.0

    instability = (
        1 if abs(load_change) > 40 else 0
    )

    # --------------------------------------------------------
    # Defense states
    # --------------------------------------------------------

    defenses = grid.get("defenses", {})

    authentication = defenses.get(
        "authentication",
        defenses.get("authGateway", False)
    )

    firewall = defenses.get(
        "firewall",
        False
    )

    anomaly_detection = defenses.get(
        "anomalyDetection",
        defenses.get("anomaly", False)
    )

    # Convert booleans to 0/1
    authentication = int(bool(authentication))
    firewall = int(bool(firewall))
    anomaly_detection = int(bool(anomaly_detection))

    # --------------------------------------------------------
    # Meter data
    # --------------------------------------------------------

    meter_values = {}

    for meter_id, meter_data in devices.items():

        if not isinstance(meter_data, dict):
            continue

        consumption = meter_data.get(
            "power_consumption",
            0
        )

        try:
            consumption = float(consumption or 0)
        except (TypeError, ValueError):
            consumption = 0.0

        meter_values[f"{meter_id}_load"] = consumption

    # --------------------------------------------------------
    # Timestamp
    # --------------------------------------------------------

    timestamp = datetime.now(
        timezone.utc
    ).isoformat()

    # --------------------------------------------------------
    # Dataset label
    # --------------------------------------------------------

    if attack and attack != "NONE":
        label = 1
    else:
        label = 0

    row = {
        "timestamp": timestamp,

        "total_load_kw": total_load,
        "total_generation_kw": total_generation,

        "load_change_kw": load_change,
        "load_ratio": load_ratio,
        "instability": instability,

        "grid_status": grid_status,
        "grid_power": grid_power,

        "attack": attack,
        "shutdown_reason": shutdown_reason,

        "max_generation_kw": max_generation,

        "authentication_gateway": authentication,
        "firewall": firewall,
        "anomaly_detection": anomaly_detection,

        "label": label,
    }

    # Add meter readings
    row.update(meter_values)

    previous_load = total_load

    return row


# ============================================================
# CSV WRITER
# ============================================================

csv_file = None
csv_writer = None
fieldnames = None


def save_row(row):
    """Append one row to the CSV dataset."""

    global csv_file
    global csv_writer
    global fieldnames

    # First row determines the columns
    if fieldnames is None:

        fieldnames = list(row.keys())

        csv_file = open(
            OUTPUT_FILE,
            "a",
            newline="",
            encoding="utf-8"
        )

        csv_writer = csv.DictWriter(
            csv_file,
            fieldnames=fieldnames
        )

        # Write header only if file is empty
        if os.path.getsize(OUTPUT_FILE) == 0:
            csv_writer.writeheader()

    # Ensure missing fields don't break CSV writing
    complete_row = {
        column: row.get(column, "")
        for column in fieldnames
    }

    csv_writer.writerow(complete_row)

    csv_file.flush()


# ============================================================
# MAIN LOOP
# ============================================================

def main():

    print("=" * 60)
    print("SMART GRID DATASET COLLECTOR")
    print("=" * 60)

    print(f"Firebase: {STATUS_ENDPOINT}")
    print(f"Output:   {OUTPUT_FILE}")
    print(f"Interval: {SAMPLE_INTERVAL} seconds")
    print()
    print("Press CTRL+C to stop.")
    print()

    sample_count = 0

    try:

        while True:

            data = get_grid_data()

            if data is not None:

                row = create_dataset_row(data)

                save_row(row)

                sample_count += 1

                print(
                    f"[{sample_count:05d}] "
                    f"Load={row['total_load_kw']:.2f} kW | "
                    f"Generation={row['total_generation_kw']:.2f} kW | "
                    f"Status={row['grid_status']} | "
                    f"Attack={row['attack']} | "
                    f"Label={row['label']}"
                )

            time.sleep(SAMPLE_INTERVAL)

    except KeyboardInterrupt:

        print()
        print("=" * 60)
        print("DATA COLLECTION STOPPED")
        print(f"Samples collected: {sample_count}")
        print(f"Dataset: {OUTPUT_FILE}")
        print("=" * 60)

    finally:

        if csv_file is not None:
            csv_file.close()


if __name__ == "__main__":
    main()