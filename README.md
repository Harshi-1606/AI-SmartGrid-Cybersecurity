# Smartgrid Project
College Major Project on Cybersecurity to smartgrid

# Changelog
### V1.0 (dashboardoperator.py) <br/>
Completed and Hardcoded basic working of the file
Has several bugs but works as intended

---
### V1.1 (dashboardoperator.py)
### [Unreleased] - <28/11/2025>
#### Changed
- Reworked network layer to use requests.Session, configurable timeouts, retries, and exponential backoff for PUT requests.
- Payload format updated to include timezone-aware ISO timestamp (`timestamp_iso`) and optional epoch field (`timestamp_epoch`).
- Added type hints and defensive input validation to `_create_payload`.
- UI styling upgraded: platform-aware fonts, more consistent ttk style configuration, and a `Value.TLabel` style for numeric displays.
- Attack console styling made configurable via `attack_bg` / `attack_fg`.
- Removed (visually) the blackout panel from main layout to simplify UI.
- Added small color helpers and utilities for theme tweaks.

### Fixed
- (None yet) — note: new version introduced several issues that must be fixed (see "Known issues").

### Known issues / TODO
- `network_worker` incorrectly uses `getattr(self, "COMMAND_ENDPOINT")` / `STATUS_ENDPOINT` — will raise on HTTP calls. Replace with module constants or assign to `self.*` in `__init__`.
- `create_widgets` removed `self.blackout_listbox` but blackout-related methods still reference it — causes `AttributeError`. Either restore the widget or guard calls.
- Color helper functions declared without `self` cause `TypeError` if called via `self.*`. Mark as `@staticmethod` or add `self`.
- Queue item unpacking is messy — simplify logic to correctly extract `(priority, payload)` pattern.

