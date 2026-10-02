#!/usr/bin/env python3

import base64
import json
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
import urllib.error
import urllib.request

from PIL import Image, ImageTk


OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3.5:9b"
ROBOT_BASE_URL = "http://192.168.2.45:8000"

MAX_STEPS = 40
IMAGE_HISTORY_LIMIT = 4

DEFAULT_MOTOR_SPEED = 700
MIN_MOTOR_SPEED = 0
MAX_MOTOR_SPEED = 1000

CAPTURE_DIR = Path(
    "robot_captures"
)

CAPTURE_DIR.mkdir(
    exist_ok=True
)


ROBOT_POLICY = """
You control a mobile robot using ONLY the provided robot primitives.

Choose exactly ONE primitive per decision.

Available primitives:
- observe(): get a fresh forward-facing camera image
- get_distance(): get ultrasonic distance straight ahead
- move_forward(distance_cm): move straight forward
- turn_left(angle_degrees): rotate left
- turn_right(angle_degrees): rotate right
- stop(): end the mission

Your job is to visually navigate to the target.

IMPORTANT RULES:

1. Always use observe() to decide where the target is.

2. After ANY movement or turn, call observe() before moving or turning again.

3. If the target is visible:
   - if it is left of center, turn_left()
   - if it is right of center, turn_right()
   - if it is near the center, move_forward()

4. Use SMALL corrections.
   - Prefer turns around 10 to 20 degrees.
   - Prefer short forward movements.
   - Do not use 45-degree or larger turns unless the target is clearly far to one side.

5. If the target was visible before but is NOT visible now:
   - do NOT move forward
   - assume the target is nearby but outside the camera view
   - continue turning in the SAME search direction
   - use small 10 to 20 degree turns
   - observe after every turn

6. Do NOT alternate left, right, left, right when searching.
   Once you start searching in one direction, keep searching in that direction
   until the target is seen again, unless there is strong evidence the search
   direction is wrong.

7. If you are unsure:
   - make a small turn
   - observe again
   - do not make a large movement

8. Use get_distance() only after the target is visually aligned approximately
   straight ahead.

9. Ultrasonic distance is only a distance measurement.
   It does NOT identify the object.

10. NEVER use one large forward movement based on ultrasonic distance.

11. When approaching the target:
   - move only a small fraction of the remaining distance
   - prefer about 5 to 15 cm per forward movement
   - when close to the target, prefer even smaller moves
   - after EVERY forward movement, call observe() again
   - re-check alignment before moving again
   - use get_distance() again when useful
   - repeat until the requested final distance is reached

12. If ultrasonic says the target is 50 cm away, do NOT move_forward(45).
    Move a small step, observe again, and verify.

13. The closer you get to the target, the smaller the movement should become.

14. Do not invent sensor readings.
    Do not claim movement happened until the tool confirms it.

15. When the target is centered and the requested stopping distance has been
    reached, call stop().

Use this control loop:

observe
-> align target
-> get_distance if aligned
-> small forward move
-> observe
-> correct alignment
-> get_distance if needed
-> small forward move
-> repeat
""".strip()


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "observe",
            "description": (
                "Capture a fresh robot-camera observation."
            ),
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_distance",
            "description": (
                "Read the real forward ultrasonic distance in cm."
            ),
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "move_forward",
            "description": (
                "Move forward by the requested distance in cm."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "distance_cm": {
                        "type": "number"
                    }
                },
                "required": [
                    "distance_cm"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "turn_left",
            "description": (
                "Turn left by the requested angle in degrees."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "angle_degrees": {
                        "type": "number"
                    }
                },
                "required": [
                    "angle_degrees"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "turn_right",
            "description": (
                "Turn right by the requested angle in degrees."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "angle_degrees": {
                        "type": "number"
                    }
                },
                "required": [
                    "angle_degrees"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stop",
            "description": (
                "Stop when the mission goal has been reached."
            ),
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


def encode_image(path):
    return base64.b64encode(
        Path(path).read_bytes()
    ).decode("utf-8")


def compact_old_images(messages):
    image_indices = [
        index
        for index, message
        in enumerate(messages)
        if message.get("images")
    ]

    keep = set(
        image_indices[
            -IMAGE_HISTORY_LIMIT:
        ]
    )

    compacted = []

    for index, message in enumerate(messages):
        copied = dict(message)

        if (
            copied.get("images")
            and index not in keep
        ):
            copied.pop(
                "images",
                None
            )

            copied["content"] = (
                "Older camera observation. "
                "Image payload removed because "
                "the rolling visual-history limit "
                "was exceeded."
            )

        compacted.append(
            copied
        )

    return compacted


class RobotGUI:
    def __init__(self, root):
        self.root = root

        self.root.title(
            "Robot Mission Control — 360 / Direction Settings"
        )

        self.root.geometry(
            "1320x900"
        )

        self.root.minsize(
            1100,
            760
        )

        self.messages = []
        self.current_tool = None
        self.current_arguments = {}
        self.current_assistant_message = None
        self.step_count = 0
        self.must_observe_after_move = False
        self.observation_paths = []

        self.manual_action = None
        self.keys_down = set()
        self.arm_busy = False

        self.worker_queue = queue.Queue()

        self.COLORS = {
            "bg": "#0B0F14",
            "panel": "#111821",
            "panel2": "#151E29",
            "border": "#263241",
            "text": "#F3F7FB",
            "muted": "#91A0B2",
            "accent": "#4DA3FF",
            "success": "#53D769",
            "warning": "#FFB84D",
            "danger": "#FF5D5D",
            "input": "#0F151D",
        }

        self.build_ui()
        self.bind_keyboard()
        self.poll_worker_queue()

    def build_ui(self):
        self.root.configure(
            bg=self.COLORS["bg"]
        )

        style = ttk.Style()

        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "Accent.TButton",
            font=("Sans", 11, "bold"),
            padding=(16, 10),
            background=self.COLORS["accent"]
        )

        style.configure(
            "Control.TButton",
            font=("Sans", 12, "bold"),
            padding=(16, 12),
            background=self.COLORS["panel2"],
            foreground=self.COLORS["text"]
        )

        style.configure(
            "Danger.TButton",
            font=("Sans", 12, "bold"),
            padding=(18, 11),
            background=self.COLORS["danger"],
            foreground="#FFFFFF"
        )

        style.configure(
            "Dark.TEntry",
            fieldbackground=self.COLORS["input"],
            foreground=self.COLORS["text"],
            insertcolor=self.COLORS["text"],
            padding=9
        )

        shell = tk.Frame(
            self.root,
            bg=self.COLORS["bg"]
        )

        shell.pack(
            fill="both",
            expand=True,
            padx=22,
            pady=18
        )

        # ---------- Header ----------

        header = tk.Frame(
            shell,
            bg=self.COLORS["bg"]
        )

        header.pack(
            fill="x",
            pady=(0, 16)
        )

        left_header = tk.Frame(
            header,
            bg=self.COLORS["bg"]
        )

        left_header.pack(
            side="left",
            fill="x",
            expand=True
        )

        tk.Label(
            left_header,
            text="ROBOT // VISION",
            bg=self.COLORS["bg"],
            fg=self.COLORS["accent"],
            font=("Sans", 10, "bold")
        ).pack(anchor="w")

        tk.Label(
            left_header,
            text="Mission Control",
            bg=self.COLORS["bg"],
            fg=self.COLORS["text"],
            font=("Sans", 28, "bold")
        ).pack(anchor="w")

        tk.Label(
            left_header,
            text=(
                "AI movement executes automatically. "
                "Manual drive and emergency stop remain available."
            ),
            bg=self.COLORS["bg"],
            fg=self.COLORS["muted"],
            font=("Sans", 10)
        ).pack(anchor="w")

        self.status_label = tk.Label(
            header,
            text="● IDLE",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            padx=14,
            pady=10,
            font=("Sans", 9, "bold")
        )

        self.status_label.pack(
            side="right"
        )

        # ---------- Mission row ----------

        mission = tk.Frame(
            shell,
            bg=self.COLORS["panel"],
            highlightbackground=self.COLORS["border"],
            highlightthickness=1,
            padx=16,
            pady=14
        )

        mission.pack(
            fill="x",
            pady=(0, 14)
        )

        tk.Label(
            mission,
            text="Goal",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Sans", 9, "bold")
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 8)
        )

        self.goal_var = tk.StringVar(
            value=(
                "Go in front of the pen stand "
                "and stop about 5 cm away."
            )
        )

        ttk.Entry(
            mission,
            textvariable=self.goal_var,
            style="Dark.TEntry"
        ).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(0, 12)
        )

        self.start_button = ttk.Button(
            mission,
            text="Start Mission",
            command=self.start_mission,
            style="Accent.TButton"
        )

        self.start_button.grid(
            row=0,
            column=2,
            padx=(0, 12)
        )

        self.top_stop_button = ttk.Button(
            mission,
            text="STOP MOTORS",
            command=self.safety_stop,
            style="Danger.TButton"
        )

        self.top_stop_button.grid(
            row=0,
            column=3
        )

        mission.columnconfigure(
            1,
            weight=1
        )

        # ---------- AI action ----------

        action = tk.Frame(
            shell,
            bg=self.COLORS["panel"],
            highlightbackground=self.COLORS["border"],
            highlightthickness=1,
            padx=18,
            pady=16
        )

        action.pack(
            fill="x",
            pady=(0, 14)
        )

        self.action_label = tk.Label(
            action,
            text="Idle",
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            font=("Sans", 22, "bold")
        )

        self.action_label.pack(anchor="w")

        self.detail_label = tk.Label(
            action,
            text="Press Start Mission when ready. AI movements execute automatically.",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Sans", 10),
            justify="left"
        )

        self.detail_label.pack(
            anchor="w",
            pady=(3, 10)
        )

        self.approval_frame = tk.Frame(
            action,
            bg=self.COLORS["panel"]
        )

        self.approval_frame.pack(
            fill="x"
        )

        self.go_var = tk.StringVar()

        self.go_entry = ttk.Entry(
            self.approval_frame,
            textvariable=self.go_var,
            style="Dark.TEntry",
            width=12
        )

        self.go_button = ttk.Button(
            self.approval_frame,
            text="GO",
            command=self.approve_ai_movement,
            style="Accent.TButton"
        )

        # ---------- Manual drive ----------

        manual = tk.Frame(
            shell,
            bg=self.COLORS["panel"],
            highlightbackground=self.COLORS["border"],
            highlightthickness=1,
            padx=18,
            pady=14
        )

        manual.pack(
            fill="x",
            pady=(0, 14)
        )

        manual_left = tk.Frame(
            manual,
            bg=self.COLORS["panel"]
        )

        manual_left.pack(
            side="left",
            padx=(0, 30)
        )

        tk.Label(
            manual_left,
            text="MANUAL DRIVE",
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            font=("Sans", 12, "bold")
        ).pack(anchor="w")

        tk.Label(
            manual_left,
            text=(
                "Mouse: press + hold direction\n"
                "Keyboard: W/A/S/D or arrows\n"
                "Release = STOP • Space/Esc = STOP"
            ),
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Sans", 9),
            justify="left"
        ).pack(
            anchor="w",
            pady=(4, 0)
        )

        drive_pad = tk.Frame(
            manual,
            bg=self.COLORS["panel"]
        )

        drive_pad.pack(
            side="left"
        )

        self.forward_button = ttk.Button(
            drive_pad,
            text="▲\nFORWARD",
            style="Control.TButton"
        )

        self.forward_button.grid(
            row=0,
            column=1,
            padx=5,
            pady=5
        )

        self.left_button = ttk.Button(
            drive_pad,
            text="◀\nLEFT",
            style="Control.TButton"
        )

        self.left_button.grid(
            row=1,
            column=0,
            padx=5,
            pady=5
        )

        self.center_stop_button = ttk.Button(
            drive_pad,
            text="■\nSTOP",
            command=self.safety_stop,
            style="Danger.TButton"
        )

        self.center_stop_button.grid(
            row=1,
            column=1,
            padx=5,
            pady=5
        )

        self.right_button = ttk.Button(
            drive_pad,
            text="▶\nRIGHT",
            style="Control.TButton"
        )

        self.right_button.grid(
            row=1,
            column=2,
            padx=5,
            pady=5
        )

        self.backward_button = ttk.Button(
            drive_pad,
            text="▼\nBACK",
            style="Control.TButton"
        )

        self.backward_button.grid(
            row=2,
            column=1,
            padx=5,
            pady=5
        )

        speed_panel = tk.Frame(
            manual,
            bg=self.COLORS["panel"]
        )

        speed_panel.pack(
            side="left",
            padx=(24, 0)
        )

        tk.Label(
            speed_panel,
            text="MOTOR SPEED",
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            font=("Sans", 10, "bold")
        ).pack(anchor="w")

        self.speed_var = tk.IntVar(
            value=DEFAULT_MOTOR_SPEED
        )

        self.speed_value_label = tk.Label(
            speed_panel,
            text=str(DEFAULT_MOTOR_SPEED),
            bg=self.COLORS["panel"],
            fg=self.COLORS["accent"],
            font=("Sans", 11, "bold")
        )

        self.speed_value_label.pack(
            anchor="w",
            pady=(2, 3)
        )

        self.speed_slider = ttk.Scale(
            speed_panel,
            from_=MIN_MOTOR_SPEED,
            to=MAX_MOTOR_SPEED,
            orient="horizontal",
            command=self.on_speed_slider
        )

        self.speed_slider.set(
            DEFAULT_MOTOR_SPEED
        )

        self.speed_slider.pack(
            fill="x",
            ipadx=70
        )

        tk.Label(
            speed_panel,
            text="0 = stop   •   1000 = max",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Sans", 8)
        ).pack(
            anchor="w",
            pady=(3, 0)
        )

        self.manual_state_label = tk.Label(
            manual,
            text="Manual motor: STOPPED",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Sans", 10, "bold"),
            padx=18
        )

        self.manual_state_label.pack(
            side="left"
        )

        self.bind_hold_button(
            self.forward_button,
            "forward"
        )

        self.bind_hold_button(
            self.backward_button,
            "backward"
        )

        self.bind_hold_button(
            self.left_button,
            "left"
        )

        self.bind_hold_button(
            self.right_button,
            "right"
        )

        self.build_arm_panel(shell)

        # ---------- Lower split ----------

        lower = tk.PanedWindow(
            shell,
            orient="horizontal",
            sashwidth=7,
            bg=self.COLORS["bg"],
            bd=0
        )

        lower.pack(
            fill="both",
            expand=True
        )

        left = tk.Frame(
            lower,
            bg=self.COLORS["panel"],
            highlightbackground=self.COLORS["border"],
            highlightthickness=1
        )

        tk.Label(
            left,
            text="Latest robot observation",
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            font=("Sans", 12, "bold"),
            padx=14,
            pady=10
        ).pack(anchor="w")

        self.preview_label = tk.Label(
            left,
            text="No image yet.",
            bg="#070A0E",
            fg=self.COLORS["muted"]
        )

        self.preview_label.pack(
            fill="both",
            expand=True,
            padx=14,
            pady=(0, 14)
        )

        right = tk.Frame(
            lower,
            bg=self.COLORS["bg"]
        )

        context_card = tk.Frame(
            right,
            bg=self.COLORS["panel"],
            highlightbackground=self.COLORS["border"],
            highlightthickness=1,
            padx=14,
            pady=12
        )

        context_card.pack(
            fill="x",
            pady=(0, 12)
        )

        self.context_label = tk.Label(
            context_card,
            text=(
                f"Visual history: "
                f"0 / {IMAGE_HISTORY_LIMIT}"
            ),
            bg=self.COLORS["panel"],
            fg=self.COLORS["accent"],
            font=("Sans", 10, "bold")
        )

        self.context_label.pack(anchor="w")

        self.context_text = tk.Text(
            context_card,
            height=5,
            bg=self.COLORS["input"],
            fg=self.COLORS["text"],
            relief="flat",
            state="disabled",
            font=("Monospace", 9)
        )

        self.context_text.pack(
            fill="x",
            pady=(8, 0)
        )

        log_card = tk.Frame(
            right,
            bg=self.COLORS["panel"],
            highlightbackground=self.COLORS["border"],
            highlightthickness=1
        )

        log_card.pack(
            fill="both",
            expand=True
        )

        tk.Label(
            log_card,
            text="Mission log",
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            font=("Sans", 12, "bold"),
            padx=14,
            pady=10
        ).pack(anchor="w")

        self.log_text = tk.Text(
            log_card,
            bg=self.COLORS["input"],
            fg="#D8E2EE",
            relief="flat",
            state="disabled",
            font=("Monospace", 9)
        )

        self.log_text.pack(
            fill="both",
            expand=True,
            padx=14,
            pady=(0, 14)
        )

        lower.add(
            left,
            minsize=500,
            stretch="always"
        )

        lower.add(
            right,
            minsize=430,
            stretch="always"
        )

    # ---------- Arm control ----------

    def build_arm_panel(self, parent):
        panel = tk.Frame(parent, bg=self.COLORS["bg"])
        panel.pack(fill="x", pady=(0, 14))
        self.arm_buttons = []
        self.arm_angles_ui = {}
        self.arm_sliders = {}
        self.arm_confirmed = {}
        self.arm_reverse = {}
        for column, joint, title, plus, minus in (
            (0, "lift", "LIFT", "UP [8]", "DOWN [4]"),
            (1, "grip", "GRIP", "OPEN [5]", "CLOSE [6]"),
        ):
            card = tk.Frame(panel, bg=self.COLORS["panel"], padx=14, pady=10,
                            highlightbackground=self.COLORS["border"], highlightthickness=1)
            card.grid(row=0, column=column, sticky="nsew", padx=(0, 7) if column == 0 else (7, 0))
            panel.columnconfigure(column, weight=1, uniform="arm")
            tk.Label(card, text=title, bg=self.COLORS["panel"], fg=self.COLORS["accent"],
                     font=("Sans", 12, "bold")).grid(row=0, column=0, sticky="w")
            confirmed = tk.Label(card, text="Last command: —", bg=self.COLORS["panel"],
                                 fg=self.COLORS["muted"], font=("Sans", 9))
            confirmed.grid(row=0, column=1, columnspan=2, sticky="e")
            self.arm_confirmed[joint] = confirmed
            var = tk.StringVar(value="90")
            self.arm_angles_ui[joint] = var
            slider = tk.Scale(card, from_=0, to=360, resolution=1, orient="horizontal",
                              showvalue=False, bg=self.COLORS["panel"], fg=self.COLORS["text"],
                              troughcolor=self.COLORS["input"], highlightthickness=0,
                              command=lambda v, j=joint: self.arm_angles_ui[j].set(str(int(float(v)))))
            self.arm_sliders[joint] = slider
            slider.set(90)
            slider.grid(row=1, column=0, columnspan=3, sticky="ew", pady=4)
            self.arm_buttons.append(slider)
            entry = ttk.Entry(card, textvariable=var, width=6, style="Dark.TEntry")
            entry.grid(row=2, column=0, sticky="w")
            entry.bind("<Return>", lambda event, j=joint: self.apply_arm_angle(j))
            self.arm_buttons.append(entry)
            tk.Label(card, text="degrees • 0–360°", bg=self.COLORS["panel"],
                     fg=self.COLORS["muted"], font=("Sans", 9)).grid(row=2, column=1, sticky="w")
            apply = ttk.Button(card, text="SET ANGLE", style="Accent.TButton",
                               command=lambda j=joint: self.apply_arm_angle(j))
            apply.grid(row=2, column=2, sticky="e")
            self.arm_buttons.append(apply)
            for col, label, action in ((0, minus, joint + ("_down" if joint == "lift" else "_close")),
                                      (2, plus, joint + ("_up" if joint == "lift" else "_open"))):
                button = ttk.Button(card, text=label, style="Control.TButton",
                                    command=lambda a=action: self.send_arm_action(a))
                button.grid(row=3, column=col, sticky="ew", pady=(6, 0))
                self.arm_buttons.append(button)
            reverse = tk.BooleanVar(value=False)
            self.arm_reverse[joint] = reverse
            toggle = tk.Checkbutton(card, text="Reverse button direction", variable=reverse,
                                    bg=self.COLORS["panel"], fg=self.COLORS["text"],
                                    selectcolor=self.COLORS["input"], activebackground=self.COLORS["panel"])
            toggle.grid(row=4, column=0, columnspan=3, sticky="w", pady=(5, 0))
            self.arm_buttons.append(toggle)
            card.columnconfigure(1, weight=1)
        self.arm_status = tk.Label(parent,
            text="0–360° input • Buttons/keypad move 1° • Reverse changes buttons, not exact angles.",
            bg=self.COLORS["bg"], fg=self.COLORS["muted"], anchor="w", font=("Sans", 9))
        self.arm_status.pack(fill="x", pady=(0, 8))

    @staticmethod
    def key_to_arm_action(keysym):
        return {
            "8": "lift_up", "KP_8": "lift_up", "KP_Up": "lift_up",
            "4": "lift_down", "KP_4": "lift_down", "KP_Left": "lift_down",
            "5": "grip_open", "KP_5": "grip_open", "KP_Begin": "grip_open",
            "6": "grip_close", "KP_6": "grip_close", "KP_Right": "grip_close",
        }.get(keysym)

    def apply_arm_angle(self, joint):
        try:
            angle = int(self.arm_angles_ui[joint].get())
            if not 0 <= angle <= 360:
                raise ValueError
        except ValueError:
            self.arm_status.configure(text="Enter a whole-number angle from 0 to 360°.",
                                      fg=self.COLORS["danger"])
            return "break"
        self.send_arm_payload({"joint": joint, "angle": angle})
        return "break"

    def send_arm_action(self, action):
        joint = action.split("_")[0]
        self.send_arm_payload({"action": action, "reverse": self.arm_reverse[joint].get()})

    def send_arm_payload(self, payload):
        if self.arm_busy:
            return
        self.arm_busy = True
        for widget in self.arm_buttons:
            widget.configure(state="disabled")
        self.arm_status.configure(text="Sending arm command…", fg=self.COLORS["accent"])
        threading.Thread(target=self.arm_worker, args=(payload,), daemon=True).start()

    def arm_worker(self, payload):
        try:
            request = urllib.request.Request(
                ROBOT_BASE_URL + "/arm", data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.loads(response.read())
            if not result.get("ok"):
                raise RuntimeError(result.get("error", "Arm command failed"))
            self.worker_queue.put({"type": "arm_updated", "result": result})
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read()).get("error", str(exc))
            except Exception:
                detail = str(exc)
            if exc.code == 404:
                detail = "Run the new robot_slave.py on the Pi: /arm is unavailable."
            self.worker_queue.put({"type": "arm_error", "message": detail})
        except Exception as exc:
            self.worker_queue.put({"type": "arm_error", "message": str(exc)})

    # ---------- Speed control ----------

    def on_speed_slider(
        self,
        raw_value
    ):
        speed = int(
            round(
                float(raw_value)
            )
        )

        self.speed_var.set(
            speed
        )

        self.speed_value_label.configure(
            text=str(speed)
        )

        # Debounce network updates while the slider is moving.
        if hasattr(
            self,
            "_speed_after_id"
        ):
            try:
                self.root.after_cancel(
                    self._speed_after_id
                )
            except Exception:
                pass

        self._speed_after_id = self.root.after(
            150,
            self.send_speed_update
        )

    def send_speed_update(
        self
    ):
        speed = int(
            self.speed_var.get()
        )

        threading.Thread(
            target=self.speed_worker,
            args=(speed,),
            daemon=True
        ).start()

    def speed_worker(
        self,
        speed
    ):
        try:
            payload = json.dumps(
                {
                    "speed": speed
                }
            ).encode(
                "utf-8"
            )

            request = urllib.request.Request(
                ROBOT_BASE_URL
                + "/speed",
                data=payload,
                headers={
                    "Content-Type":
                        "application/json"
                },
                method="POST"
            )

            with urllib.request.urlopen(
                request,
                timeout=3
            ) as response:
                result = json.loads(
                    response.read()
                )

            if not result.get(
                "ok"
            ):
                raise RuntimeError(
                    result.get(
                        "error",
                        "Speed update failed."
                    )
                )

            self.worker_queue.put(
                {
                    "type":
                        "speed_updated",
                    "speed":
                        int(
                            result[
                                "motor_speed"
                            ]
                        )
                }
            )

        except Exception as exc:
            self.worker_queue.put(
                {
                    "type":
                        "speed_error",
                    "message":
                        str(exc)
                }
            )

    # ---------- Manual drive ----------

    def bind_hold_button(
        self,
        button,
        action
    ):
        button.bind(
            "<ButtonPress-1>",
            lambda event, a=action:
                self.start_manual_motion(a)
        )

        button.bind(
            "<ButtonRelease-1>",
            lambda event:
                self.stop_manual_motion()
        )

        button.bind(
            "<Leave>",
            lambda event:
                self.stop_manual_motion()
        )

    def bind_keyboard(self):
        self.root.bind(
            "<KeyPress>",
            self.on_key_press
        )

        self.root.bind(
            "<KeyRelease>",
            self.on_key_release
        )

    def focus_is_text_input(self):
        widget = self.root.focus_get()

        return isinstance(
            widget,
            (
                tk.Entry,
                ttk.Entry,
                tk.Text
            )
        )

    def key_to_action(
        self,
        keysym
    ):
        mapping = {
            "w": "forward",
            "Up": "forward",
            "s": "backward",
            "Down": "backward",
            "a": "left",
            "Left": "left",
            "d": "right",
            "Right": "right",
        }

        return mapping.get(
            keysym
        )

    def on_key_press(
        self,
        event
    ):
        if event.keysym in (
            "Escape",
            "space"
        ):
            self.safety_stop()
            return "break"

        if self.focus_is_text_input():
            return

        arm_action = self.key_to_arm_action(event.keysym)
        if arm_action is not None:
            if event.keysym not in self.keys_down:
                self.keys_down.add(event.keysym)
                self.send_arm_action(arm_action)
            return "break"

        action = self.key_to_action(
            event.keysym
        )

        if action is None:
            return

        # Ignore keyboard auto-repeat.
        if event.keysym in self.keys_down:
            return "break"

        self.keys_down.add(
            event.keysym
        )

        self.start_manual_motion(
            action
        )

        return "break"

    def on_key_release(
        self,
        event
    ):
        if self.key_to_arm_action(event.keysym) is not None:
            self.keys_down.discard(event.keysym)
            return "break"

        action = self.key_to_action(
            event.keysym
        )

        if action is None:
            return

        self.keys_down.discard(
            event.keysym
        )

        # We only support one direction at a time.
        self.stop_manual_motion()

        return "break"

    def start_manual_motion(
        self,
        action
    ):
        if self.manual_action == action:
            return

        # Always stop any previous direction first.
        if self.manual_action is not None:
            self.stop_manual_motion()

        self.manual_action = action

        self.manual_state_label.configure(
            text=(
                f"Manual motor: "
                f"{action.upper()}"
            ),
            fg=self.COLORS[
                "warning"
            ]
        )

        threading.Thread(
            target=self.manual_start_worker,
            args=(action,),
            daemon=True
        ).start()

    def manual_start_worker(
        self,
        action
    ):
        try:
            payload = json.dumps(
                {
                    "action": action
                }
            ).encode(
                "utf-8"
            )

            request = urllib.request.Request(
                ROBOT_BASE_URL
                + "/manual",
                data=payload,
                headers={
                    "Content-Type":
                        "application/json"
                },
                method="POST"
            )

            with urllib.request.urlopen(
                request,
                timeout=3
            ) as response:
                result = json.loads(
                    response.read()
                )

            if not result.get(
                "ok"
            ):
                raise RuntimeError(
                    result.get(
                        "error",
                        "Manual movement failed."
                    )
                )

            self.worker_queue.put(
                {
                    "type":
                        "manual_started",
                    "action":
                        action
                }
            )

        except Exception as exc:
            self.worker_queue.put(
                {
                    "type":
                        "manual_error",
                    "message":
                        str(exc)
                }
            )

    def stop_manual_motion(
        self
    ):
        self.manual_action = None

        self.manual_state_label.configure(
            text="Manual motor: STOPPING",
            fg=self.COLORS[
                "danger"
            ]
        )

        threading.Thread(
            target=self.stop_worker,
            daemon=True
        ).start()

    def safety_stop(
        self
    ):
        self.manual_action = None
        self.keys_down.clear()

        self.manual_state_label.configure(
            text="Manual motor: STOPPING",
            fg=self.COLORS[
                "danger"
            ]
        )

        threading.Thread(
            target=self.stop_worker,
            daemon=True
        ).start()

    def stop_worker(
        self
    ):
        try:
            request = urllib.request.Request(
                ROBOT_BASE_URL
                + "/stop",
                data=b"",
                method="POST"
            )

            with urllib.request.urlopen(
                request,
                timeout=3
            ) as response:
                result = json.loads(
                    response.read()
                )

            self.worker_queue.put(
                {
                    "type":
                        "stopped",
                    "ok":
                        bool(
                            result.get(
                                "ok"
                            )
                        )
                }
            )

        except Exception as exc:
            self.worker_queue.put(
                {
                    "type":
                        "stop_error",
                    "message":
                        str(exc)
                }
            )

    # ---------- Utility UI ----------

    def log(
        self,
        text
    ):
        self.log_text.configure(
            state="normal"
        )

        self.log_text.insert(
            "end",
            text + "\n"
        )

        self.log_text.see(
            "end"
        )

        self.log_text.configure(
            state="disabled"
        )

    def update_context(
        self
    ):
        retained = (
            self.observation_paths[
                -IMAGE_HISTORY_LIMIT:
            ]
        )

        self.context_label.configure(
            text=(
                f"Visual history: "
                f"{len(retained)} / "
                f"{IMAGE_HISTORY_LIMIT}"
            )
        )

        self.context_text.configure(
            state="normal"
        )

        self.context_text.delete(
            "1.0",
            "end"
        )

        for path in retained:
            self.context_text.insert(
                "end",
                Path(path).name
                + "\n"
            )

        self.context_text.configure(
            state="disabled"
        )

    def show_go(
        self
    ):
        self.go_var.set("")

        self.go_entry.pack(
            side="left"
        )

        self.go_button.pack(
            side="left",
            padx=(8, 0)
        )

        self.go_entry.focus_set()

    def hide_go(
        self
    ):
        self.go_entry.pack_forget()
        self.go_button.pack_forget()

    # ---------- AI mission ----------

    def start_mission(
        self
    ):
        goal = (
            self.goal_var
            .get()
            .strip()
        )

        if not goal:
            messagebox.showerror(
                "Missing goal",
                "Enter a mission goal."
            )
            return

        self.messages = [
            {
                "role":
                    "system",
                "content":
                    ROBOT_POLICY
            },
            {
                "role":
                    "user",
                "content":
                    goal
            }
        ]

        self.step_count = 0
        self.observation_paths = []
        self.must_observe_after_move = False

        self.log(
            f"USER: {goal}"
        )

        self.start_button.configure(
            state="disabled"
        )

        self.request_model()

    def request_model(
        self
    ):
        if (
            self.step_count
            >= MAX_STEPS
        ):
            self.fail(
                "Maximum step count reached."
            )
            return

        self.step_count += 1

        messages = compact_old_images(
            self.messages
        )

        self.status_label.configure(
            text="● THINKING",
            fg=self.COLORS[
                "accent"
            ]
        )

        self.action_label.configure(
            text="Qwen is deciding..."
        )

        self.hide_go()

        threading.Thread(
            target=self.model_worker,
            args=(messages,),
            daemon=True
        ).start()

    def model_worker(
        self,
        messages
    ):
        try:
            payload = {
                "model":
                    MODEL,
                "messages":
                    messages,
                "tools":
                    TOOLS,
                "think":
                    False,
                "stream":
                    False,
                "options": {
                    "temperature":
                        0,
                    "num_ctx": 8192
                }
            }

            request = urllib.request.Request(
                OLLAMA_URL,
                data=json.dumps(
                    payload
                ).encode(
                    "utf-8"
                ),
                headers={
                    "Content-Type":
                        "application/json"
                },
                method="POST"
            )

            start = (
                time.perf_counter()
            )

            with urllib.request.urlopen(
                request,
                timeout=120
            ) as response:
                result = json.loads(
                    response.read()
                )

            latency_ms = (
                time.perf_counter()
                - start
            ) * 1000.0

            message = result.get(
                "message",
                {}
            )

            tool_calls = message.get(
                "tool_calls",
                []
            )

            if not tool_calls:
                raise RuntimeError(
                    "Model returned no tool call."
                )

            function = (
                tool_calls[0]
                .get(
                    "function",
                    {}
                )
            )

            self.worker_queue.put(
                {
                    "type":
                        "model",
                    "tool":
                        function.get(
                            "name"
                        ),
                    "arguments":
                        function.get(
                            "arguments",
                            {}
                        ),
                    "assistant_message":
                        message,
                    "latency_ms":
                        latency_ms
                }
            )

        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode(
                    "utf-8",
                    errors="replace"
                )
            except Exception:
                body = ""

            message = (
                f"Ollama HTTP {exc.code}: "
                f"{exc.reason}"
            )

            if body:
                message += (
                    "\n\nOllama response:\n"
                    + body
                )

            self.worker_queue.put(
                {
                    "type":
                        "error",
                    "message":
                        message
                }
            )

        except Exception as exc:
            self.worker_queue.put(
                {
                    "type":
                        "error",
                    "message":
                        str(exc)
                }
            )

    def handle_model(
        self,
        item
    ):
        self.current_tool = (
            item["tool"]
        )

        self.current_arguments = (
            item["arguments"]
        )

        self.current_assistant_message = (
            item[
                "assistant_message"
            ]
        )

        tool = self.current_tool
        args = self.current_arguments

        self.log(
            f"AI: {tool}{args} "
            f"({item['latency_ms']:.0f} ms)"
        )

        if (
            self.must_observe_after_move
            and tool != "observe"
        ):
            self.messages.append(
                {
                    "role":
                        "user",
                    "content": (
                        "The robot moved. "
                        "Call observe() now."
                    )
                }
            )

            self.request_model()
            return

        if tool == "observe":
            self.action_label.configure(
                text="OBSERVING"
            )

            self.detail_label.configure(
                text=(
                    "Fetching fresh robot image."
                )
            )

            self.capture()
            return

        if tool == "get_distance":
            self.action_label.configure(
                text="READING DISTANCE"
            )

            self.detail_label.configure(
                text=(
                    "Reading ultrasonic sensor."
                )
            )

            self.read_distance()
            return

        if tool in (
            "move_forward",
            "turn_left",
            "turn_right"
        ):
            if tool == "move_forward":
                description = (
                    "MOVE FORWARD "
                    f"{args.get('distance_cm')} cm"
                )

            elif tool == "turn_left":
                description = (
                    "TURN LEFT "
                    f"{args.get('angle_degrees')}°"
                )

            else:
                description = (
                    "TURN RIGHT "
                    f"{args.get('angle_degrees')}°"
                )

            self.action_label.configure(
                text=description
            )

            self.detail_label.configure(
                text=(
                    "Executing AI movement now..."
                )
            )

            self.status_label.configure(
                text="● AI MOVING",
                fg=self.COLORS[
                    "warning"
                ]
            )

            self.hide_go()

            threading.Thread(
                target=self.ai_movement_worker,
                daemon=True
            ).start()

            return

        if tool == "stop":
            self.messages.append(
                self.current_assistant_message
            )

            self.action_label.configure(
                text="MISSION COMPLETE",
                fg=self.COLORS[
                    "success"
                ]
            )

            self.status_label.configure(
                text="● COMPLETE",
                fg=self.COLORS[
                    "success"
                ]
            )

            self.safety_stop()
            return

        self.fail(
            f"Unknown tool: {tool}"
        )

    def approve_ai_movement(
        self
    ):
        if (
            self.go_var
            .get()
            .strip()
            .upper()
            != "GO"
        ):
            messagebox.showwarning(
                "Approval required",
                "Type GO exactly."
            )
            return

        self.hide_go()

        self.status_label.configure(
            text="● AI MOVING",
            fg=self.COLORS[
                "warning"
            ]
        )

        self.action_label.configure(
            text="MOVING..."
        )

        threading.Thread(
            target=self.ai_movement_worker,
            daemon=True
        ).start()

    def ai_movement_worker(
        self
    ):
        try:
            tool = self.current_tool
            args = self.current_arguments

            if tool == "move_forward":
                value = args[
                    "distance_cm"
                ]
            else:
                value = args[
                    "angle_degrees"
                ]

            payload = {
                "action":
                    tool,
                "value":
                    value
            }

            request = urllib.request.Request(
                ROBOT_BASE_URL
                + "/move",
                data=json.dumps(
                    payload
                ).encode(
                    "utf-8"
                ),
                headers={
                    "Content-Type":
                        "application/json"
                },
                method="POST"
            )

            with urllib.request.urlopen(
                request,
                timeout=10
            ) as response:
                result = json.loads(
                    response.read()
                )

            if not result.get(
                "ok"
            ):
                raise RuntimeError(
                    result.get(
                        "error",
                        "AI movement failed."
                    )
                )

            self.worker_queue.put(
                {
                    "type":
                        "ai_movement",
                    "tool":
                        tool,
                    "value":
                        value
                }
            )

        except Exception as exc:
            self.safety_stop()

            self.worker_queue.put(
                {
                    "type":
                        "error",
                    "message":
                        str(exc)
                }
            )

    def finish_ai_movement(
        self,
        item
    ):
        tool = item[
            "tool"
        ]

        value = item[
            "value"
        ]

        self.messages.append(
            self.current_assistant_message
        )

        if tool == "move_forward":
            result = (
                f"Forward movement of "
                f"{value} cm completed."
            )
        elif tool == "turn_left":
            result = (
                f"Left turn of "
                f"{value} degrees completed."
            )
        else:
            result = (
                f"Right turn of "
                f"{value} degrees completed."
            )

        self.messages.append(
            {
                "role":
                    "tool",
                "tool_name":
                    tool,
                "content":
                    result
            }
        )

        self.must_observe_after_move = True

        self.log(
            f"TOOL: {result}"
        )

        self.request_model()

    # ---------- Camera ----------

    def capture(
        self
    ):
        threading.Thread(
            target=self.capture_worker,
            daemon=True
        ).start()

    def capture_worker(
        self
    ):
        try:
            timestamp = int(
                time.time()
                * 1000
            )

            image_path = (
                CAPTURE_DIR
                / (
                    f"observation_"
                    f"{timestamp}.jpg"
                )
            )

            with urllib.request.urlopen(
                ROBOT_BASE_URL
                + "/observe.jpg",
                timeout=20
            ) as response:
                image_bytes = (
                    response.read()
                )

            image_path.write_bytes(
                image_bytes
            )

            self.worker_queue.put(
                {
                    "type":
                        "capture",
                    "image_path":
                        str(
                            image_path
                        )
                }
            )

        except Exception as exc:
            self.worker_queue.put(
                {
                    "type":
                        "error",
                    "message":
                        str(exc)
                }
            )

    def finish_capture(
        self,
        image_path
    ):
        self.show_preview(
            image_path
        )

        self.observation_paths.append(
            image_path
        )

        self.update_context()

        self.messages.append(
            self.current_assistant_message
        )

        # Keep the tool result itself text-only.
        # Some Ollama/model combinations reject image payloads on role="tool"
        # with HTTP 400. The actual camera frame is sent in a following
        # user-role multimodal message instead.
        self.messages.append(
            {
                "role":
                    "tool",
                "tool_name":
                    "observe",
                "content": (
                    "observe() completed successfully. "
                    f"Image file: {Path(image_path).name}"
                )
            }
        )

        self.messages.append(
            {
                "role":
                    "user",
                "content": (
                    "This image is the fresh camera observation "
                    "returned by observe()."
                ),
                "images": [
                    encode_image(
                        image_path
                    )
                ]
            }
        )

        self.must_observe_after_move = False

        self.log(
            f"TOOL: observe() -> "
            f"{image_path}"
        )

        self.request_model()

    # ---------- Ultrasonic ----------

    def read_distance(
        self
    ):
        threading.Thread(
            target=self.distance_worker,
            daemon=True
        ).start()

    def distance_worker(
        self
    ):
        try:
            with urllib.request.urlopen(
                ROBOT_BASE_URL
                + "/distance",
                timeout=10
            ) as response:
                result = json.loads(
                    response.read()
                )

            if not result.get(
                "ok"
            ):
                raise RuntimeError(
                    result.get(
                        "error",
                        "Distance failed."
                    )
                )

            self.worker_queue.put(
                {
                    "type":
                        "distance",
                    "distance_cm":
                        float(
                            result[
                                "distance_cm"
                            ]
                        )
                }
            )

        except Exception as exc:
            self.worker_queue.put(
                {
                    "type":
                        "error",
                    "message":
                        str(exc)
                }
            )

    def finish_distance(
        self,
        distance_cm
    ):
        self.messages.append(
            self.current_assistant_message
        )

        result = (
            f"Ultrasonic distance is "
            f"{distance_cm:.1f} cm."
        )

        self.messages.append(
            {
                "role":
                    "tool",
                "tool_name":
                    "get_distance",
                "content":
                    result
            }
        )

        self.log(
            f"TOOL: {result}"
        )

        self.request_model()

    # ---------- Preview ----------

    def show_preview(
        self,
        image_path
    ):
        try:
            image = Image.open(
                image_path
            )

            image.thumbnail(
                (540, 400),
                Image.Resampling.LANCZOS
            )

            photo = ImageTk.PhotoImage(
                image
            )

            self.preview_label.configure(
                image=photo,
                text=""
            )

            self.preview_label.image = photo

        except Exception as exc:
            self.preview_label.configure(
                image="",
                text=str(exc)
            )

    # ---------- Worker queue ----------

    def poll_worker_queue(
        self
    ):
        try:
            while True:
                item = (
                    self.worker_queue
                    .get_nowait()
                )

                item_type = (
                    item["type"]
                )

                if item_type == "model":
                    self.handle_model(
                        item
                    )

                elif item_type == "capture":
                    self.finish_capture(
                        item[
                            "image_path"
                        ]
                    )

                elif item_type == "distance":
                    self.finish_distance(
                        item[
                            "distance_cm"
                        ]
                    )

                elif item_type == "ai_movement":
                    self.finish_ai_movement(
                        item
                    )

                elif item_type in ("arm_updated", "arm_error"):
                    self.arm_busy = False
                    for button in self.arm_buttons:
                        button.configure(state="normal")
                    if item_type == "arm_updated":
                        result = item["result"]
                        joint = result.get("joint")
                        if joint in self.arm_confirmed:
                            angle = result[joint + "_angle"]
                            self.arm_confirmed[joint].configure(text=f"Last command: {angle}°")
                            self.arm_sliders[joint].set(angle)
                            self.arm_angles_ui[joint].set(str(angle))
                        message = (f"Lift: {result['lift_angle']}°  •  "
                                   f"Grip: {result['grip_angle']}° (commanded)")
                        color = self.COLORS["success"]
                    else:
                        message = "Arm error: " + item["message"]
                        color = self.COLORS["danger"]
                    self.arm_status.configure(text=message, fg=color)
                    self.log(message)

                elif item_type == "speed_updated":
                    speed = item[
                        "speed"
                    ]

                    self.speed_var.set(
                        speed
                    )

                    self.speed_value_label.configure(
                        text=str(
                            speed
                        )
                    )

                    self.log(
                        f"MOTOR SPEED: {speed}"
                    )

                elif item_type == "speed_error":
                    messagebox.showerror(
                        "Speed update failed",
                        item[
                            "message"
                        ]
                    )

                elif item_type == "manual_started":
                    action = item[
                        "action"
                    ]

                    self.log(
                        f"MANUAL: {action}"
                    )

                elif item_type == "stopped":
                    self.manual_state_label.configure(
                        text=(
                            "Manual motor: STOPPED"
                        ),
                        fg=self.COLORS[
                            "muted"
                        ]
                    )

                    self.log(
                        "MOTORS: stopped"
                    )

                elif item_type == "manual_error":
                    self.manual_state_label.configure(
                        text=(
                            "Manual motor: ERROR"
                        ),
                        fg=self.COLORS[
                            "danger"
                        ]
                    )

                    messagebox.showerror(
                        "Manual drive error",
                        item[
                            "message"
                        ]
                    )

                elif item_type == "stop_error":
                    self.manual_state_label.configure(
                        text=(
                            "STOP FAILED"
                        ),
                        fg=self.COLORS[
                            "danger"
                        ]
                    )

                    messagebox.showerror(
                        "Stop failed",
                        item[
                            "message"
                        ]
                    )

                elif item_type == "error":
                    self.fail(
                        item[
                            "message"
                        ]
                    )

        except queue.Empty:
            pass

        self.root.after(
            100,
            self.poll_worker_queue
        )

    def fail(
        self,
        message
    ):
        self.status_label.configure(
            text="● STOPPED",
            fg=self.COLORS[
                "danger"
            ]
        )

        self.action_label.configure(
            text="TEST STOPPED",
            fg=self.COLORS[
                "danger"
            ]
        )

        self.detail_label.configure(
            text=message
        )

        self.hide_go()

        self.start_button.configure(
            state="normal"
        )

        self.log(
            "ERROR: "
            + message
        )

        self.safety_stop()


def main():
    root = tk.Tk()
    RobotGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()


