import tkinter as tk
from tkinter import ttk, scrolledtext
import requests
import threading
import queue
import time
from datetime import datetime, timedelta

# --- Configuration ---
FIREBASE_URL = "https://trip-a155a-default-rtdb.asia-southeast1.firebasedatabase.app/"
COMMAND_ENDPOINT = FIREBASE_URL + "command.json"
STATUS_ENDPOINT = FIREBASE_URL + "status.json"

# DEFENSES
DEFENSE_INFO = {
    "authentication": {"title": "Authentication Gateway", "icon": "🔑"},
    "replay": {"title": "Temporal Firewall", "icon": "⏳"},
    "anomaly": {"title": "Anomaly Detection", "icon": "📈"}
}

class OperatorDashboardApp:
    def __init__(self, root):
        self.root = root
        self.root.title("OPERATOR DASHBOARD [SECURE TERMINAL]")
        self.root.geometry("1200x820")
        self.root.configure(bg="#2c3e50")

        self.request_queue = queue.PriorityQueue()
        self.response_queue = queue.Queue()
        self.is_running = True
        self.auth_token = "SECURE_TOKEN_123"

        # Active blackouts: meterID -> expiry datetime
        self.active_blackouts = {}
        self.blackout_default_duration = 20.0  # seconds

        self._setup_styles()
        self.create_widgets()

        # Network thread
        self.network_thread = threading.Thread(target=self.network_worker, daemon=True)
        self.network_thread.start()

        # process responses and cleanup loops
        self.process_response_queue()
        self.root.after(1000, self._cleanup_blackouts_loop)

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    # ---------------------------
    # Payload and network
    # ---------------------------
    def _create_payload(self, command, targetID="", value=0.0):
        return {
            "command": command,
            "targetID": targetID,
            "value": float(value),
            "authToken": self.auth_token,
            "timestamp": datetime.now().timestamp(),
            "fromOperator": True,
            "hash": "DISABLED"
        }

    def network_worker(self):
        last_poll_time = 0
        while self.is_running:
            try:
                # send queued commands
                try:
                    _priority, payload = self.request_queue.get(block=False)
                    try:
                        requests.put(COMMAND_ENDPOINT, json=payload, timeout=3)
                    except Exception as e:
                        # network error while sending — show in attack console
                        self.log_attack_action(f"Send Error: {e}")
                except queue.Empty:
                    pass

                # poll status periodically
                if time.time() - last_poll_time > 0.5:
                    last_poll_time = time.time()
                    try:
                        resp = requests.get(STATUS_ENDPOINT, timeout=2)
                        if resp.status_code == 200:
                            self.response_queue.put(resp.json())
                    except Exception:
                        pass

                time.sleep(0.05)
            except Exception:
                time.sleep(1)

    # ---------------------------
    # UI creation (single tab)
    # ---------------------------
    def _setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.bg_color = "#ecf0f1"
        self.style.configure(".", background=self.bg_color)
        self.style.configure("TLabel", background=self.bg_color, font=("Segoe UI", 10))
        self.style.configure("TButton", font=("Segoe UI", 10, "bold"))
        self.style.configure("Value.TLabel", font=("Consolas", 14, "bold"), foreground="#2980b9")

    def create_widgets(self):
        container = ttk.Frame(self.root)
        container.pack(fill="both", expand=True, padx=12, pady=12)

        # top area: left controls, right meters + consoles
        top = ttk.Frame(container)
        top.pack(fill="both", expand=False)

        left = ttk.Frame(top)
        left.pack(side="left", fill="y", padx=(0,10))

        right = ttk.Frame(top)
        right.pack(side="left", fill="both", expand=True)

        # -------------------------
        # Left: Master Controls + Defense Buttons
        # -------------------------
        master_frame = ttk.LabelFrame(left, text="Master Lighting & Defenses", padding=12)
        master_frame.pack(fill="y", expand=False)

        # Lighting controls
        lc = ttk.LabelFrame(master_frame, text="Master Lighting Control", padding=8)
        lc.pack(fill="x", pady=(0,8))

        self.cv_on = tk.Canvas(lc, width=28, height=28, bg=self.bg_color, highlightthickness=0)
        self.cv_on.pack(side="left", padx=(6,8))
        self._draw_light_indicator(self.cv_on, "#bdc3c7")

        ttk.Button(lc, text="ACTIVATE ALL LIGHTS", width=22, command=lambda: self.send_command("SET_LIGHTS", value=1.0)).pack(side="left", padx=6, pady=4)

        self.cv_off = tk.Canvas(lc, width=28, height=28, bg=self.bg_color, highlightthickness=0)
        self.cv_off.pack(side="left", padx=(6,8))
        self._draw_light_indicator(self.cv_off, "#bdc3c7")

        ttk.Button(lc, text="DEACTIVATE ALL LIGHTS", width=22, command=lambda: self.send_command("SET_LIGHTS", value=0.0)).pack(side="left", padx=6, pady=4)

        # Defense buttons area (three buttons only as requested)
        def_frame = ttk.LabelFrame(master_frame, text="Defense Toggles", padding=8)
        def_frame.pack(fill="x", pady=(6,8))

        # We'll create three toggle buttons and an indicator label for each
        self.def_buttons = {}
        self.def_labels = {}

        for key in ["authentication", "replay", "anomaly"]:
            sub = ttk.Frame(def_frame)
            sub.pack(fill="x", pady=4)

            lbl_icon = ttk.Label(sub, text=f"{DEFENSE_INFO[key]['icon']} {DEFENSE_INFO[key]['title']}", width=24, anchor="w")
            lbl_icon.pack(side="left")

            # status label (ACTIVE/DISABLED)
            st = ttk.Label(sub, text="UNKNOWN", width=10)
            st.pack(side="left", padx=(6,6))
            self.def_labels[key] = st

            # toggle button
            btn = ttk.Button(sub, text="Toggle", width=10, command=lambda k=key: self.send_command("SET_DEFENSE", targetID=k))
            btn.pack(side="right")
            self.def_buttons[key] = btn

        # -------------------------
        # Right: Meters table + Attack console + Active Blackouts
        # -------------------------
        meters_frame = ttk.LabelFrame(right, text="Meters & Grid Status", padding=8)
        meters_frame.pack(fill="both", expand=True)

        # top metrics row
        metrics = ttk.Frame(meters_frame)
        metrics.pack(fill="x", pady=(0,8))

        ttk.Label(metrics, text="Generation Output:").pack(side="left", padx=(4,6))
        self.lbl_gen = ttk.Label(metrics, text="0.00 kW", style="Value.TLabel")
        self.lbl_gen.pack(side="left", padx=(0,18))

        ttk.Label(metrics, text="Current Load:").pack(side="left", padx=(4,6))
        self.lbl_con = ttk.Label(metrics, text="0.00 kW", style="Value.TLabel")
        self.lbl_con.pack(side="left", padx=(0,18))

        ttk.Label(metrics, text="System Status:").pack(side="left", padx=(4,6))
        self.lbl_status = ttk.Label(metrics, text="WAITING", font=("Segoe UI", 12, "bold"))
        self.lbl_status.pack(side="left", padx=(0,6))

        # meters table
        cols = ("id", "loc", "val")
        self.tree = ttk.Treeview(meters_frame, columns=cols, show="headings", height=12)
        self.tree.heading("id", text="Meter ID"); self.tree.column("id", width=140)
        self.tree.heading("loc", text="Zone"); self.tree.column("loc", width=120)
        self.tree.heading("val", text="Load (kW)"); self.tree.column("val", width=120)
        self.tree.pack(fill="both", expand=False, pady=(0,8))

        # bottom: attack console + active blackouts side-by-side
        bottom = ttk.Frame(meters_frame)
        bottom.pack(fill="both", expand=True)

        attack_pan = ttk.LabelFrame(bottom, text="Attack Console", padding=6)
        attack_pan.pack(side="left", fill="both", expand=True)

        self.attack_console = scrolledtext.ScrolledText(attack_pan, height=12, bg="#000", fg="#f39c12", font=("Consolas", 10))
        self.attack_console.pack(fill="both", expand=True)

        blackout_pan = ttk.LabelFrame(bottom, text="Acit", padding=6, width=220)
       

        self.blackout_listbox = tk.Listbox(blackout_pan, height=12, width=28)
        self.blackout_listbox.pack(fill="both", expand=True)

    # ---------------------------
    # UI helpers & logging
    # ---------------------------
    def _draw_light_indicator(self, canvas, color):
        canvas.delete("all")
        canvas.create_oval(2, 2, 26, 26, outline="#7f8c8d", width=1)
        canvas.create_oval(5, 5, 23, 23, fill=color, outline=color)

    def _append_attack_log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.attack_console.insert("end", f"[{ts}] {msg}\n")
        self.attack_console.see("end")

    def log_attack_action(self, msg):
        # route defense messages here as well (defense log removed)
        self._append_attack_log(msg)

    # ---------------------------
    # Commands: send to firebase
    # ---------------------------
    def send_command(self, cmd, targetID="", value=0.0):
        payload = self._create_payload(cmd, targetID, value)
        self.request_queue.put((1, payload))

    # ---------------------------
    # Response processing
    # ---------------------------
    def process_response_queue(self):
        try:
            while not self.response_queue.empty():
                data = self.response_queue.get_nowait()
                if data:
                    # update UI
                    self.update_dashboard(data)
                    self.process_logs(data.get("log", ""))
        finally:
            if self.is_running:
                self.root.after(100, self.process_response_queue)

    def process_logs(self, log_msg):
        if not log_msg:
            return

        # Defense logs — now shown in attack console
        if "[DEFENSE]" in log_msg:
            # still update labels via update_dashboard; also log here
            self.log_attack_action(log_msg)

        # Attack keywords
        attack_keywords = ("CRITICAL", "BLACKOUT", "DDoS", "DDOS", "INSTABILITY", "Tamper", "TAMPER")
        if any(k.upper() in log_msg.upper() for k in attack_keywords):
            self.log_attack_action(log_msg)

            # try to parse targeted blackout meter
            lm = log_msg.upper()
            if "TARGETED BLACKOUT" in lm or "METER:" in lm:
                start = lm.find("METER:")
                if start != -1:
                    rest = lm[start+6:].strip()
                    meter_id = rest.split()[0].strip(").,;:")
                    if meter_id:
                        expiry = datetime.now() + timedelta(seconds=self.blackout_default_duration)
                        self._add_active_blackout(meter_id, expiry)

        # Show other logs also in attack console
        if "[DEFENSE]" not in log_msg and not any(k.upper() in log_msg.upper() for k in attack_keywords):
            self.log_attack_action(log_msg)

    # ---------------------------
    # Dashboard updater
    # ---------------------------
    def update_dashboard(self, data):
        # must run on UI thread
        def do_update():
            self.lbl_gen.config(text=f"{data.get('totalGeneration', 0):.2f} kW")
            total_load = 0
            self.tree.delete(*self.tree.get_children())
            for m in data.get("meters", []):
                val = m.get("consumption", 0)
                self.tree.insert("", "end", values=(m.get('id', ''), m.get('location', ''), f"{val:.2f}"))
                total_load += val

            self.lbl_con.config(text=f"{total_load:.2f} kW")
            status = data.get('gridStatus', "UNKNOWN")
            self.lbl_status.config(text=status, foreground="green" if status == "STABLE" else "red")

            if total_load > 0.5:
                self._draw_light_indicator(self.cv_on, "#2ecc71")
                self._draw_light_indicator(self.cv_off, "#bdc3c7")
            else:
                self._draw_light_indicator(self.cv_on, "#bdc3c7")
                self._draw_light_indicator(self.cv_off, "#e74c3c")

            # Update defense labels
            for key in ["authentication", "replay", "anomaly"]:
                active = bool(data.get(f"{key}Active", False))
                lbl = self.def_labels.get(key)
                if lbl:
                    lbl.config(text="ACTIVE" if active else "DISABLED",
                               foreground="#27ae60" if active else "#c0392b")

        self.root.after(0, do_update)

    # ---------------------------
    # Active blackouts management
    # ---------------------------
    def _add_active_blackout(self, meter_id, expiry_dt):
        def do_add():
            self.active_blackouts[meter_id] = expiry_dt
            self._refresh_blackout_listbox()
        self.root.after(0, do_add)

    def _refresh_blackout_listbox(self):
        self.blackout_listbox.delete(0, tk.END)
        items = sorted(self.active_blackouts.items(), key=lambda kv: kv[1])
        for meter_id, expiry in items:
            secs = int(max(0, (expiry - datetime.now()).total_seconds()))
            self.blackout_listbox.insert(tk.END, f"{meter_id}  (expires in {secs}s)")

    def _cleanup_blackouts_loop(self):
        try:
            now = datetime.now()
            removed = []
            for meter_id, expiry in list(self.active_blackouts.items()):
                if expiry <= now:
                    removed.append(meter_id)
                    del self.active_blackouts[meter_id]
            if removed:
                for m in removed:
                    self.log_attack_action(f"Targeted blackout ended (Meter: {m})")
                self._refresh_blackout_listbox()
        finally:
            if self.is_running:
                self.root.after(1000, self._cleanup_blackouts_loop)

    # ---------------------------
    # Finish / Close
    # ---------------------------
    def on_closing(self):
        self.is_running = False
        self.root.destroy()

# ---------------------------
# Run
# ---------------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = OperatorDashboardApp(root)
    root.mainloop()
