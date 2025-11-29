# Import statements: Loads UI library (Tkinter + themed widgets), HTTP requests library, 
# threading/queue/time utilities, and date/time helpers.

import tkinter as tk
from tkinter import ttk, scrolledtext
from tkinter import font as tkfont
import requests
import threading
import queue
import time
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict,Any, Optional
from requests import Session, RequestException
from json import JSONDecodeError

# --- Configuration ---
FIREBASE_URL = "https://trip-a155a-default-rtdb.asia-southeast1.firebasedatabase.app/" # Firebase url
COMMAND_ENDPOINT = FIREBASE_URL + "command.json" # Adds command.json to the end of firebase url
STATUS_ENDPOINT = FIREBASE_URL + "status.json" # Adds status.json to the end of firebase url

# DEFENSES
# Small dict mapping three defense names to a label and emoji icon.
# This part of code is displayed in Defense toggle
DEFENSE_INFO = {
    "authentication": {"title": "Authentication Gateway", "icon": "🔑"},
    "replay": {"title": "Temporal Firewall", "icon": "⏳"},
    "anomaly": {"title": "Anomaly Detection", "icon": "📈"}
}

class OperatorDashboardApp:
    def __init__(self, root):
        # Saves root (Tk window), sets title/size/background.
        self.root = root
        self.root.title("OPERATOR DASHBOARD [SECURE TERMINAL]")
        self.root.geometry("1200x820")
        self.root.configure(bg="#2c3e50")

        # Creates request_queue (priority queue) for outbound commands and 
        # response_queue for inbound data from network thread.
        self.request_queue = queue.PriorityQueue()
        self.response_queue = queue.Queue()
        # is_running controls the background thread.
        self.is_running = True
        # auth_token is the token placed into outgoing payloads.
        self.auth_token = "SECURE_TOKEN_123"

        # Active blackouts: stores meterID -> expiry datetime
        self.active_blackouts = {}
        self.blackout_default_duration = 20.0  # seconds (need to change to take input from user)

        # NEW response queue controller settings
        self.response_poll_interval_ms = getattr(self, "response_poll_interval_ms", 100)      # normal interval
        self.response_max_items_per_tick = getattr(self, "response_max_items_per_tick", 8)    # max items to handle per tick
        self.response_short_backlog_ms = getattr(self, "response_short_backlog_ms", 20)       # re-run quickly when backlog
        self._response_after_id = None   # will hold after() id so we can cancel on shutdown

        # NEW: Logging system defaults
        self.attack_console_max_lines = 2000
        self.attack_log_file = None

        # Calls styling and widget creation function
        self._setup_styles()
        self.create_widgets()

        # Network thread
        # Starts a background network_thread (daemon) to handle HTTP I/O.
        self.network_thread = threading.Thread(target=self.network_worker, daemon=True)
        self.network_thread.start()

        # process responses and cleanup loops
        self.process_response_queue() # Starts loop (runs every 100ms) to handle responses
        self.root.after(1000, self._cleanup_blackouts_loop) # Expires blackout

        # used to close tkinter window by clicking X(close) button
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    # ---------------------------
    # Payload and network
    # ---------------------------
    # Creates JSON payload to send to Firebase
    def _create_payload(self, command: str, targetID: str="", value: float | int =0.0, include_epoch: bool = True) -> Dict[str, Any]: # Defines a method
        if not isinstance(command, str) or not command: # Check if command is valid string
            raise ValueError("command must be a non-empty string")

        try:
            value_f = float(value) # Convert value to float
        except (TypeError, ValueError):
            raise ValueError("value must be convertible to float")

        now = datetime.now(timezone.utc) # Get current time with timezone
        payload = { # Creates dictionary
            "command": command,
            "targetID": targetID,
            "value": value_f,
            "authToken": getattr(self, "auth_token", None),
            "timestamp_iso": now.isoformat(),          # readable and timezone-aware
            "fromOperator": True,
            "hash": "DISABLED"
        }
        if include_epoch: # Adds epoch timestamp if needed
            payload["timestamp_epoch"] = now.timestamp()

        return payload

    def network_worker(self): # Function runs in background
        # Configurable parameters with same defaults
        poll_interval = getattr(self, "net_poll_interval", 0.5)       # seconds between polls
        send_timeout = getattr(self, "send_timeout", 3.0)             # timeout for PUT
        status_timeout = getattr(self, "status_timeout", 2.0)         # timeout for GET status
        max_send_retries = getattr(self, "max_send_retries", 2)       # retries for sending
        queue_get_timeout = getattr(self, "queue_get_timeout", 0.2)   # short blocking wait
        retry_base_delay = getattr(self, "retry_base_delay", 0.25)    # base backoff seconds
        requeue_on_fail = getattr(self, "requeue_on_fail", True)     # whether to requeue failed payloads

        last_poll_time = 0.0
        session = Session()  # connection pooling

        try:
            while getattr(self, "is_running", False):
                # allow external stop_event if provided (faster shutdown)
                stop_event = getattr(self, "stop_event", None)
                if stop_event is not None and stop_event.is_set():
                    break

                # 1) Send one queued command (non-blocking-ish)
                try:
                    # small timeout so we can periodically check is_running/polling
                    item = self.request_queue.get(timeout=queue_get_timeout)
                except queue.Empty:
                    item = None

                if item is not None:
                    try:
                        # If using a PriorityQueue it will be (priority, payload)
                        if isinstance(item, tuple) and len(item) >= 2:
                            _, payload = item[0], item[1]  # tolerate priority or (prio, payload)
                        # if queue.item is (prio,payload) but sometimes user enqueued differently:
                            if len(item) >= 2:
                                payload = item[1]
                        else:
                            payload = item  # fallback: item itself
                    except Exception:
                        payload = item  # be forgiving

                    # send with limited retries + exponential backoff
                    success = False
                    attempt = 0
                    while attempt <= max_send_retries and not success and getattr(self, "is_running", False):
                        try:
                            attempt += 1
                            session.put(getattr(self, "COMMAND_ENDPOINT"), json=payload, timeout=send_timeout)
                            success = True
                        except RequestException as e:
                            # network/transient error
                            self.log_attack_action(f"Send Error (attempt {attempt}): {e}")
                            if attempt <= max_send_retries:
                                # exponential backoff
                                delay = retry_base_delay * (2 ** (attempt - 1))
                                time.sleep(delay)
                            else:
                                # exhausted retries
                                if requeue_on_fail:
                                    try:
                                        # requeue at end (no priority)
                                        self.request_queue.put((9999, payload))
                                    except Exception:
                                        # if requeue fails, log and drop
                                        self.log_attack_action("Failed to requeue payload after retries")
                                # not raising here — continue main loop

                    # if using task_done pattern (producer used join()), call task_done
                    try:
                        self.request_queue.task_done()
                    except Exception:
                        pass

                # 2) Poll status endpoint at configured interval
                now = time.monotonic()
                if now - last_poll_time >= poll_interval:
                    last_poll_time = now
                    try:
                        resp = session.get(getattr(self, "STATUS_ENDPOINT"), timeout=status_timeout)
                        if resp.status_code == 200:
                            try:
                                data = resp.json()
                                # push to response queue without blocking indefinitely
                                try:
                                    self.response_queue.put_nowait(data)
                                except queue.Full:
                                    # if response queue is full, drop and log (or block briefly if you prefer)
                                    self.log_attack_action("Response queue full — dropping status update")
                            except JSONDecodeError:
                                self.log_attack_action("Status response JSON decode error")
                        else:
                            # non-200 response: optionally log
                            self.log_attack_action(f"Status poll returned code {resp.status_code}")
                    except RequestException as e:
                        # network error while polling: log at debug/info level
                        # avoid noisy repeated logs; consider tracking consecutive failures to throttle
                        self.log_attack_action(f"Status poll error: {e}")

                # 3) Sleep a short time to yield CPU (avoid 100% busy loop)
                # We already used blocking queue.get(timeout=...) which will sleep,
                # but adding a small sleep here reduces tight loop in case of many iterations.
                time.sleep(0.02)

        except Exception as ex:
            # Last-resort safety — log the exception and exit the thread loop after a short pause.
            try:
                self.log_attack_action(f"Network worker unhandled exception: {ex}")
            except Exception:
                pass
            # small sleep before stopping to avoid crash-loop
            time.sleep(1)
        finally:
            # cleanup session
            try:
                session.close()
            except Exception:
                pass

    # ---------------------------
    # UI creation (single tab)
    # ---------------------------
    def _setup_styles(self) -> Dict[str, object]:
        # ---- style & theme ----
        self.style = ttk.Style()

        # prefer "clam" but fall back to a safe available theme
        preferred = "clam"
        available = self.style.theme_names()
        if preferred in available:
            try:
                self.style.theme_use(preferred)
            except Exception:
                # some platforms/themes may raise — fall back to default
                self.style.theme_use(self.style.theme_use())
        else:
            # choose a safe theme (first available)
            self.style.theme_use(available[0])

        # ---- colors ----
        self.bg_color = "#ecf0f1"       # main background
        self.accent_color = "#2980b9"   # accent / value color
        self.fg_color = "#333333"       # default foreground for labels

        # ---- fonts (use system-appropriate fallbacks) ----
        if sys.platform.startswith("win"):
            ui_font_family = "Segoe UI"
        elif sys.platform == "darwin":
            ui_font_family = "Helvetica"   # San Francisco isn't always exposed directly
        else:
            ui_font_family = "DejaVu Sans"  # common Linux fallback

        # create Font objects (lets Tk handle DPI scaling)
        self.font_ui = tkfont.Font(family=ui_font_family, size=10)
        self.font_ui_bold = tkfont.Font(family=ui_font_family, size=10, weight="bold")
        self.font_mono = tkfont.Font(family="Consolas" if sys.platform.startswith("win") else "DejaVu Sans Mono", size=14, weight="bold")

        # ---- base widget styles (explicit classes) ----
        # Frame background
        self.style.configure("TFrame", background=self.bg_color)

        # Labels
        self.style.configure("TLabel",
                            background=self.bg_color,
                            foreground=self.fg_color,
                            font=self.font_ui)

        # Buttons
        self.style.configure("TButton",
                            font=self.font_ui_bold,
                            padding=(6, 4))  # give a bit of padding

        # Button visual feedback (hover/active) - map uses theme element states
        try:
            self.style.map("TButton",
                        foreground=[("active", self.fg_color), ("disabled", "#888")],
                        background=[("active", "!disabled", self._lighten(self.bg_color, 0.03)),
                                    ("pressed", "!disabled", self._lighten(self.bg_color, -0.03))])
        except Exception:
            # Some themes restrict background mapping, so ignore failures
            pass

        # Entry
        self.style.configure("TEntry",
                            fieldbackground="#ffffff",
                            background="#ffffff",
                            font=self.font_ui)

        # Treeview (if used)
        self.style.configure("Treeview",
                            background="#ffffff",
                            fieldbackground="#ffffff",
                            font=self.font_ui)
        self.style.configure("Treeview.Heading", font=self.font_ui_bold)

        # Custom "Value" label style for big numeric values
        self.style.configure("Value.TLabel",
                            background=self.bg_color,
                            font=self.font_mono,
                            foreground=self.accent_color)

        # Optional: set default padding for labels to make layout consistent
        self.style.configure("TLabel", padding=(2, 2))

        # Return commonly used constants for tests or for other parts of app
        constants = {
            "style": self.style,
            "bg_color": self.bg_color,
            "accent_color": self.accent_color,
            "fg_color": self.fg_color,
            "font_ui": self.font_ui,
            "font_ui_bold": self.font_ui_bold,
            "font_mono": self.font_mono
        }
        return constants

    # Helper: small color adjuster (very tiny dependency, placed here for convenience)
    def _hex_to_rgb(hexc: str):
        hexc = hexc.lstrip("#")
        return tuple(int(hexc[i:i+2], 16) for i in (0, 2, 4))

    def _rgb_to_hex(rgb):
        return "#{:02x}{:02x}{:02x}".format(*rgb)

    def _clamp(self, v, a=0, b=255):
        return max(a, min(b, int(v)))

    def _lighten_color(self, hexc: str, amount: float):
        """
        Lighten or darken hex color by a small amount (-0.5..0.5)
        amount > 0 -> lighter, amount < 0 -> darker
        """
        hexc = hexc.lstrip("#")
        r = int(hexc[0:2], 16)
        g = int(hexc[2:4], 16)
        b = int(hexc[4:6], 16)
        r = self._clamp(r + (255 - r) * amount)
        g = self._clamp(g + (255 - g) * amount)
        b = self._clamp(b + (255 - b) * amount)
        return "#{:02x}{:02x}{:02x}".format(r, g, b)

# Attach helper to the module-level so _setup_styles can call it (or bind to self if you prefer)
# If you place this method inside a class, implement self._lighten delegating to _lighten_color().

    def create_widgets(self):
        PAD_X = 12
        PAD_Y = 8
        SMALL_PAD = 6
        LABEL_WIDTH = 24
        STATUS_WIDTH = 10
        BTN_WIDTH = 10

        # container
        container = ttk.Frame(self.root)
        container.pack(fill="both", expand=True, padx=12, pady=12)

        # top area
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

        # on indicator
        self.cv_on = tk.Canvas(lc, width=28, height=28, bg=self.bg_color, highlightthickness=0)
        self.cv_on.pack(side="left", padx=(6,8))
        self._draw_light_indicator(self.cv_on, "#bdc3c7")

        ttk.Button(lc,
                text="ACTIVATE ALL LIGHTS",
                width=22,
                command=lambda: self.send_command("SET_LIGHTS", value=1.0)).pack(side="left", padx=6, pady=4)

        # off indicator
        self.cv_off = tk.Canvas(lc, width=28, height=28, bg=self.bg_color, highlightthickness=0)
        self.cv_off.pack(side="left", padx=(6,8))
        self._draw_light_indicator(self.cv_off, "#bdc3c7")

        ttk.Button(lc,
                text="DEACTIVATE ALL LIGHTS",
                width=22,
                command=lambda: self.send_command("SET_LIGHTS", value=0.0)).pack(side="left", padx=6, pady=4)

        # Defense buttons
        def_frame = ttk.LabelFrame(master_frame, text="Defense Toggles", padding=8)
        def_frame.pack(fill="x", pady=(6,8))

        self.def_buttons = {}
        self.def_labels = {}

        for key in ["authentication", "replay", "anomaly"]:
            sub = ttk.Frame(def_frame)
            sub.pack(fill="x", pady=4)

            lbl_icon = ttk.Label(sub, text=f"{DEFENSE_INFO[key]['icon']} {DEFENSE_INFO[key]['title']}", width=LABEL_WIDTH, anchor="w")
            lbl_icon.pack(side="left")

            st = ttk.Label(sub, text="UNKNOWN", width=STATUS_WIDTH)
            st.pack(side="left", padx=(6,6))
            self.def_labels[key] = st

            btn = ttk.Button(sub, text="Toggle", width=BTN_WIDTH, command=lambda k=key: self.send_command("SET_DEFENSE", targetID=k))
            btn.pack(side="right")
            self.def_buttons[key] = btn

        # -------------------------
        # Right: Meters table + Attack console
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

        # bottom: attack console (no blackout panel)
        bottom = ttk.Frame(meters_frame)
        bottom.pack(fill="both", expand=True)

        attack_pan = ttk.LabelFrame(bottom, text="Attack Console", padding=6)
        attack_pan.pack(side="left", fill="both", expand=True)

        # Use instance color constants so dark-mode can update these later
        attack_bg = getattr(self, "attack_bg", "#000")
        attack_fg = getattr(self, "attack_fg", "#f39c12")
        self.attack_console = scrolledtext.ScrolledText(
            attack_pan,
            height=12,
            bg=attack_bg,
            fg=attack_fg,
            font=(self.font_mono.actual("family"), 10),
            wrap = "word",
            padx = 6, pady = 4,
            borderwidth = 0
        )
        self.attack_console.pack(fill="both", expand=True)

        # Apply non-ttk widget theming (useful for dark mode toggles)
        try:
            self._apply_non_ttk_theme()
        except Exception:
            pass


    # ---------------------------
    # UI helpers & logging
    # ---------------------------
    def _draw_light_indicator(self,
                          canvas: tk.Canvas,
                          color: str,
                          size: int = 28,
                          border: str = "#7f8c8d",
                          outline_width: int = 1,
                          glow: bool = False,
                          blink: bool = False,
                          blink_interval: int = 600):
        # Cancel any previous blink job stored on the canvas
        try:
            if hasattr(canvas, "_blink_job") and canvas._blink_job is not None:
                canvas.after_cancel(canvas._blink_job)
                canvas._blink_job = None
        except Exception:
            pass

        # Compute coordinates with a small padding
        padding = 2
        w = size
        h = size
        x0, y0 = padding, padding
        x1, y1 = padding + w, padding + h

        # Keep consistent tag names so we can update/replace only those items
        tag_outer = "indicator_outer"
        tag_inner = "indicator_inner"
        tag_glow = "indicator_glow"

        # Remove previous indicator drawings only (don't clear entire canvas)
        canvas.delete(tag_outer)
        canvas.delete(tag_inner)
        canvas.delete(tag_glow)

        # Outer ring (frame)
        canvas.create_oval(x0, y0, x1, y1, outline=border, width=outline_width, tags=(tag_outer,))

        # Inner filled circle with small inset
        inset = max(3, int(size * 0.18))
        canvas.create_oval(x0 + inset, y0 + inset, x1 - inset, y1 - inset,
                        fill=color, outline=color, tags=(tag_inner,))

        # Optional glow: draw a larger, low-opacity-like ring (Tk doesn't support alpha)
        # So we simulate a glow by drawing a slightly larger ring with a lighter color.
        if glow:
            try:
                glow_amount = 0.08  # small lightening factor
                lighter = self._lighten_color(color, glow_amount)  # assumes you have _lighten_color
            except Exception:
                lighter = color
            glow_padding = max(1, int(size * 0.08))
            canvas.create_oval(x0 - glow_padding, y0 - glow_padding,
                               x1 + glow_padding, y1 + glow_padding,
                               outline=lighter, width=max(1, outline_width), tags=(tag_glow,))

        # Resize the canvas to fit the indicator if necessary
        try:
            canvas.config(width=size + padding*2, height=size + padding*2)
        except Exception:
            pass

        # Blink animation (toggle inner circle visibility)
        if blink:
            # initial visible state
            canvas.itemconfigure(tag_inner, state="normal")

            def _toggle_blink():
                cur_state = canvas.itemcget(tag_inner, "state")
                new_state = "hidden" if cur_state == "normal" else "normal"
                try:
                    canvas.itemconfigure(tag_inner, state=new_state)
                except Exception:
                    pass
                # schedule next toggle and remember job id on canvas
                canvas._blink_job = canvas.after(blink_interval, _toggle_blink)

            # start toggling
            canvas._blink_job = canvas.after(blink_interval, _toggle_blink)
        else:
            # Ensure inner item is visible if not blinking
            try:
                canvas.itemconfigure(tag_inner, state="normal")
            except Exception:
                pass
            canvas._blink_job = None

        # Optional: return the tag names or the ids if caller wants them
        return {"outer_tag": tag_outer, "inner_tag": tag_inner, "glow_tag": tag_glow}

    def _append_attack_log(self, msg):
        """
        Deprecated helper kept for compatibility.
        Delegates to append_attack_log which is thread-safe.
        """
        self.append_attack_log(msg, level="INFO")
    
    def append_attack_log(self, msg: str, level: str = "INFO"):
        """
        Public, thread-safe method to append a log line to the attack console.
        Safe to call from background threads. level: "INFO","WARNING","ERROR","CRITICAL","DEFENSE".
        """
        ts = datetime.now().strftime("%H:%M:%S")
        text = f"[{ts}] {msg}\n"

        try:
            # If already on GUI thread, insert directly (faster)
            if threading.current_thread() is threading.main_thread():
                self._insert_attack_text(text, level)
            else:
            # schedule insertion on GUI thread
                self.root.after(0, self._insert_attack_text, text, level)
        except Exception:
            # best effort fallback: try scheduling, otherwise print to stdout so logs aren't lost
            try:
                self.root.after(0, self._insert_attack_text, text, level)
            except Exception:
                print(text, end="")
    def _insert_attack_text(self, text: str, level: str):
        """
        Inserts text into the ScrolledText attack console.
        Must run on GUI thread. Handles tag setup, trimming and optional file write.
        """
        # lazy tag configuration
        if not getattr(self, "_attack_console_tags_configured", False):
            try:
                self.attack_console.tag_configure("INFO", foreground=getattr(self, "attack_fg", "#f39c12"))
                self.attack_console.tag_configure("DEFENSE", foreground="#9b59b6")
                self.attack_console.tag_configure("WARNING", foreground="#f39c12")
                # ERROR and CRITICAL get bolder font; font_mono should exist from _setup_styles
                self.attack_console.tag_configure(
                    "ERROR",
                    foreground="#e74c3c",
                    font=(self.font_mono.actual("family"), 10, "bold")
                )
                self.attack_console.tag_configure(
                    "CRITICAL",
                    foreground="#ffffff",
                    background="#c0392b",
                    font=(self.font_mono.actual("family"), 10, "bold")
                )
            except Exception:
                # tag config may fail in some headless/test environments; ignore
                pass
            self._attack_console_tags_configured = True

        # enable, insert, disable — keep the widget read-only for users
        try:
            self.attack_console.configure(state="normal")
        except Exception:
            pass

        tag = (level or "INFO").upper() if isinstance(level, str) else "INFO"
        if tag not in ("INFO", "DEFENSE", "WARNING", "ERROR", "CRITICAL"):
            tag = "INFO"

        try:
            # preferred: insert with tag (colored)
            self.attack_console.insert("end", text, tag)
            self.attack_console.see("end")
        except Exception:
            # fallback: try without tag
            try:
                self.attack_console.insert("end", text)
                self.attack_console.see("end")
            except Exception:
                # ultimate fallback: print to stdout
                print(text, end="")

        # trim old lines to keep the widget responsive
        try:
            max_lines = int(getattr(self, "attack_console_max_lines", 2000) or 2000)
            idx = self.attack_console.index("end-1c")
            if isinstance(idx, str) and "." in idx:
                num_lines = int(idx.split(".")[0])
            else:
                num_lines = 1
            if num_lines > max_lines:
                self.attack_console.delete("1.0", f"{num_lines - max_lines + 1}.0")
        except Exception:
            pass

        try:
            self.attack_console.configure(state="disabled")
        except Exception:
            pass

        # optional persistent logging
        logfile = getattr(self, "attack_log_file", None)
        if logfile:
            try:
                with open(logfile, "a", encoding="utf-8") as f:
                    f.write(text)
            except Exception:
                pass

    def log_attack_action(self, msg):
        """
        Route defense messages here as well.
        Uses the thread-safe append_attack_log so callers from background threads are safe.
        """
        # defense messages use a separate tag
        self.append_attack_log(msg, level="DEFENSE")

    # ---------------------------
    # Commands: send to firebase
    # ---------------------------
    def send_command(self, cmd: str, targetID: str = "", value: float = 0.0, priority: int = 1):
        """
        Safely create and enqueue a command payload for the network thread.
        """

        if not isinstance(cmd, str) or not cmd.strip():
            self.append_attack_log("Invalid command name provided.", "ERROR")
            return

        if not isinstance(targetID, str):
            self.append_attack_log("targetID must be a string.", "ERROR")
            return

        try:
            payload = self._create_payload(cmd, targetID, value)
        except Exception as e:
            self.append_attack_log(f"Payload creation failed: {e}", "ERROR")
            return

        try:
            self.request_queue.put((priority, payload))
            self.append_attack_log(f"Queued command: {cmd} → {targetID}", "INFO")
        except Exception as e:
            self.append_attack_log(f"Failed to queue '{cmd}': {e}", "ERROR")


    # ---------------------------
    # Response processing
    # ---------------------------
    def process_response_queue(self):
        """
        Process a bounded number of items from response_queue on the GUI thread,
        then schedule the next run adaptively (short delay if backlog remains).
        """
        try:
            processed = 0
            max_items = getattr(self, "response_max_items_per_tick", 8)

            while processed < max_items:
                try:
                    data = self.response_queue.get_nowait()
                except queue.Empty:
                    break

                try:
                    if data:
                        # Safe update_dashboard
                        try:
                            self.update_dashboard(data)
                        except Exception as e:
                            try:
                                self.append_attack_log(f"update_dashboard failed: {e}", "ERROR")
                            except Exception:
                                pass

                        # Safe process_logs
                        try:
                            self.process_logs(data.get("log", ""))
                        except Exception as e:
                            try:
                                self.append_attack_log(f"process_logs failed: {e}", "ERROR")
                            except Exception:
                                pass

                finally:
                    try:
                        self.response_queue.task_done()
                    except Exception:
                        pass

                processed += 1

        finally:
            # If app running, schedule next tick
            if getattr(self, "is_running", False):
                try:
                    backlog = not self.response_queue.empty()
                except Exception:
                    backlog = False

                # adaptive delay
                if backlog:
                    next_delay = getattr(self, "response_short_backlog_ms", 20)
                else:
                    next_delay = getattr(self, "response_poll_interval_ms", 100)

                try:
                    self._response_after_id = self.root.after(next_delay, self.process_response_queue)
                except Exception:
                    # fallback to default
                    try:
                        self._response_after_id = self.root.after(100, self.process_response_queue)
                    except Exception:
                        self._response_after_id = None
            else:
                # no scheduling when not running
                try:
                    if self._response_after_id is not None:
                        self.root.after_cancel(self._response_after_id)
                except Exception:
                    pass
                self._response_after_id = None

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
