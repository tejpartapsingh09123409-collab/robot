#!/usr/bin/env python3

import base64
import json
import queue
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
import urllib.request
import urllib.error


OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3.5:9b"

DEFAULT_CAMERA = "/dev/video2"
MAX_STEPS = 40
IMAGE_HISTORY_LIMIT = 4

ROBOT_POLICY = """
You control a mobile robot using ONLY the provided robot primitives.

The user's message gives you the mission goal.

Important interface semantics:

- Choose exactly one primitive per decision.
- observe() returns the robot's current camera view.
- get_distance() returns a real distance measurement directly ahead.
- turn_left(), turn_right(), and move_forward() physically change the robot pose.
- stop() ends the mission.
- Do not invent observations, distances, or completed movements. Wait for the
  environment to return the corresponding tool result.
- Camera images are observations, not distance measurements. Use get_distance()
  whenever you need an actual physical distance.
- After the robot physically moves or turns, an older camera image describes the
  previous pose. Use fresh observations when you need to know what the robot now
  sees.
- Previous observations and actions remain part of the conversation history.
  Use that history to reason about what has already been seen and done.

You are responsible for the navigation/search strategy and for deciding which
primitive to call next. The environment does not provide a hard-coded search
strategy or movement plan.

For this test, a human physically executes movement primitives and supplies
sensor results. Treat those tool results exactly as real robot feedback.
""".strip()

CAPTURE_DIR = Path("human_robot_captures")
CAPTURE_DIR.mkdir(exist_ok=True)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "observe",
            "description": (
                "Capture a new camera observation of the current scene. "
                "Use this whenever visual information is missing, stale, "
                "or you want to verify alignment after movement."
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
                "Get the measured distance directly ahead in centimeters."
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
                "Move the robot straight forward by the requested "
                "distance in centimeters."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "distance_cm": {
                        "type": "number"
                    }
                },
                "required": ["distance_cm"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "turn_left",
            "description": (
                "Turn the robot left/counter-clockwise by the "
                "requested number of degrees."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "angle_degrees": {
                        "type": "number"
                    }
                },
                "required": ["angle_degrees"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "turn_right",
            "description": (
                "Turn the robot right/clockwise by the "
                "requested number of degrees."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "angle_degrees": {
                        "type": "number"
                    }
                },
                "required": ["angle_degrees"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stop",
            "description": (
                "Stop when the requested goal has been reached."
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
    """
    Keep a rolling window of recent camera images in the Ollama request.

    All action/tool history remains in the conversation. For camera observations,
    the newest IMAGE_HISTORY_LIMIT observations keep their actual image payloads.
    Older image payloads are removed only to keep the multimodal context bounded;
    their place in the history is retained as text.

    This lets the model visually compare several recent viewpoints and notice
    loops/revisits instead of seeing only the newest frame.
    """
    image_indices = [
        index
        for index, message in enumerate(messages)
        if message.get("images")
    ]

    keep_image_indices = set(
        image_indices[-IMAGE_HISTORY_LIMIT:]
    )

    compacted = []

    for index, message in enumerate(messages):
        copied = dict(message)

        if (
            copied.get("images")
            and index not in keep_image_indices
        ):
            copied.pop("images", None)
            copied["content"] = (
                "Older camera observation. Its image payload was removed "
                "only because the rolling visual-history window was exceeded."
            )

        compacted.append(copied)

    return compacted


class HumanRobotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Human Robot Test")
        self.root.geometry("980x760")

        self.messages = []
        self.current_tool = None
        self.current_arguments = {}
        self.current_assistant_message = None
        self.step_count = 0
        self.must_observe_after_move = False
        self.observation_paths = []

        self.worker_queue = queue.Queue()

        self.build_ui()
        self.poll_worker_queue()

    def build_ui(self):
        # ---------- palette ----------
        self.COLORS = {
            "bg": "#0B0F14",
            "panel": "#111821",
            "panel_2": "#151E29",
            "border": "#263241",
            "text": "#F3F7FB",
            "muted": "#91A0B2",
            "accent": "#4DA3FF",
            "accent_hover": "#6BB2FF",
            "success": "#53D769",
            "warning": "#FFB84D",
            "danger": "#FF5D5D",
            "input": "#0F151D",
        }

        self.root.configure(
            bg=self.COLORS["bg"]
        )

        self.root.geometry("1320x860")
        self.root.minsize(1100, 720)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "Dark.TFrame",
            background=self.COLORS["bg"]
        )
        style.configure(
            "Card.TFrame",
            background=self.COLORS["panel"]
        )
        style.configure(
            "SubCard.TFrame",
            background=self.COLORS["panel_2"]
        )
        style.configure(
            "Dark.TLabel",
            background=self.COLORS["bg"],
            foreground=self.COLORS["text"]
        )
        style.configure(
            "Card.TLabel",
            background=self.COLORS["panel"],
            foreground=self.COLORS["text"]
        )
        style.configure(
            "Muted.TLabel",
            background=self.COLORS["panel"],
            foreground=self.COLORS["muted"]
        )
        style.configure(
            "Action.TLabel",
            background=self.COLORS["panel"],
            foreground=self.COLORS["text"],
            font=("Sans", 24, "bold")
        )
        style.configure(
            "Accent.TButton",
            font=("Sans", 11, "bold"),
            padding=(16, 10),
            background=self.COLORS["accent"],
            foreground="#06111D",
            borderwidth=0
        )
        style.map(
            "Accent.TButton",
            background=[
                ("active", self.COLORS["accent_hover"]),
                ("disabled", "#33465A")
            ],
            foreground=[
                ("disabled", "#8392A2")
            ]
        )
        style.configure(
            "Secondary.TButton",
            font=("Sans", 10, "bold"),
            padding=(13, 9),
            background=self.COLORS["panel_2"],
            foreground=self.COLORS["text"],
            borderwidth=1
        )
        style.map(
            "Secondary.TButton",
            background=[
                ("active", "#202B38")
            ]
        )
        style.configure(
            "Dark.TEntry",
            fieldbackground=self.COLORS["input"],
            foreground=self.COLORS["text"],
            insertcolor=self.COLORS["text"],
            bordercolor=self.COLORS["border"],
            lightcolor=self.COLORS["border"],
            darkcolor=self.COLORS["border"],
            padding=9
        )

        shell = tk.Frame(
            self.root,
            bg=self.COLORS["bg"]
        )
        shell.pack(
            fill="both",
            expand=True,
            padx=24,
            pady=20
        )

        # ---------- header ----------
        header = tk.Frame(
            shell,
            bg=self.COLORS["bg"]
        )
        header.pack(
            fill="x",
            pady=(0, 18)
        )

        header_left = tk.Frame(
            header,
            bg=self.COLORS["bg"]
        )
        header_left.pack(
            side="left",
            fill="x",
            expand=True
        )

        tk.Label(
            header_left,
            text="HUMAN // ROBOT",
            bg=self.COLORS["bg"],
            fg=self.COLORS["accent"],
            font=("Sans", 10, "bold")
        ).pack(
            anchor="w"
        )

        tk.Label(
            header_left,
            text="Mission Control",
            bg=self.COLORS["bg"],
            fg=self.COLORS["text"],
            font=("Sans", 28, "bold")
        ).pack(
            anchor="w",
            pady=(1, 2)
        )

        tk.Label(
            header_left,
            text=(
                "Qwen decides. You execute the physical primitive. "
                "The full recent visual context goes back to the model."
            ),
            bg=self.COLORS["bg"],
            fg=self.COLORS["muted"],
            font=("Sans", 10)
        ).pack(
            anchor="w"
        )

        header_right = tk.Frame(
            header,
            bg=self.COLORS["panel"],
            highlightbackground=self.COLORS["border"],
            highlightthickness=1,
            padx=14,
            pady=10
        )
        header_right.pack(
            side="right"
        )

        tk.Label(
            header_right,
            text=MODEL,
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            font=("Sans", 10, "bold")
        ).pack(
            anchor="e"
        )

        self.header_status_label = tk.Label(
            header_right,
            text="●  IDLE",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Sans", 9, "bold")
        )
        self.header_status_label.pack(
            anchor="e",
            pady=(2, 0)
        )

        # ---------- mission setup ----------
        setup = tk.Frame(
            shell,
            bg=self.COLORS["panel"],
            highlightbackground=self.COLORS["border"],
            highlightthickness=1,
            padx=18,
            pady=16
        )
        setup.pack(
            fill="x",
            pady=(0, 14)
        )

        tk.Label(
            setup,
            text="Mission",
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            font=("Sans", 13, "bold")
        ).grid(
            row=0,
            column=0,
            columnspan=4,
            sticky="w",
            pady=(0, 12)
        )

        tk.Label(
            setup,
            text="Goal",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Sans", 9, "bold")
        ).grid(
            row=1,
            column=0,
            sticky="w",
            padx=(0, 10)
        )

        self.goal_var = tk.StringVar(
            value=(
                "Go in front of the pen stand "
                "and stop about 5 cm away."
            )
        )

        self.goal_entry = ttk.Entry(
            setup,
            textvariable=self.goal_var,
            style="Dark.TEntry"
        )
        self.goal_entry.grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(0, 18)
        )

        tk.Label(
            setup,
            text="Camera",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Sans", 9, "bold")
        ).grid(
            row=1,
            column=2,
            sticky="w",
            padx=(0, 10)
        )

        self.camera_var = tk.StringVar(
            value=DEFAULT_CAMERA
        )

        self.camera_entry = ttk.Entry(
            setup,
            textvariable=self.camera_var,
            style="Dark.TEntry",
            width=16
        )
        self.camera_entry.grid(
            row=1,
            column=3,
            sticky="ew"
        )

        setup.columnconfigure(
            1,
            weight=1
        )

        button_row = tk.Frame(
            setup,
            bg=self.COLORS["panel"]
        )
        button_row.grid(
            row=2,
            column=0,
            columnspan=4,
            sticky="w",
            pady=(14, 0)
        )

        self.start_button = ttk.Button(
            button_row,
            text="Start Mission",
            command=self.start_mission,
            style="Accent.TButton"
        )
        self.start_button.pack(
            side="left"
        )

        self.reset_button = ttk.Button(
            button_row,
            text="Reset",
            command=self.reset,
            style="Secondary.TButton"
        )
        self.reset_button.pack(
            side="left",
            padx=(10, 0)
        )

        # ---------- current action card ----------
        action_card = tk.Frame(
            shell,
            bg=self.COLORS["panel"],
            highlightbackground=self.COLORS["border"],
            highlightthickness=1,
            padx=20,
            pady=18
        )
        action_card.pack(
            fill="x",
            pady=(0, 14)
        )

        action_top = tk.Frame(
            action_card,
            bg=self.COLORS["panel"]
        )
        action_top.pack(
            fill="x"
        )

        tk.Label(
            action_top,
            text="CURRENT AI REQUEST",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Sans", 9, "bold")
        ).pack(
            side="left"
        )

        self.step_label = tk.Label(
            action_top,
            text="Decision 0 / 40",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Sans", 9)
        )
        self.step_label.pack(
            side="right"
        )

        self.action_label = tk.Label(
            action_card,
            text="Idle",
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            font=("Sans", 24, "bold")
        )
        self.action_label.pack(
            anchor="w",
            pady=(8, 3)
        )

        self.detail_label = tk.Label(
            action_card,
            text="Press Start Mission when the scene is ready.",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Sans", 10),
            justify="left",
            wraplength=1180
        )
        self.detail_label.pack(
            anchor="w",
            pady=(0, 13)
        )

        self.action_controls = tk.Frame(
            action_card,
            bg=self.COLORS["panel"]
        )
        self.action_controls.pack(
            fill="x"
        )

        self.action_button = ttk.Button(
            self.action_controls,
            text="",
            state="disabled",
            command=self.handle_action_button,
            style="Accent.TButton"
        )
        self.action_button.pack(
            side="left"
        )

        self.distance_frame = tk.Frame(
            self.action_controls,
            bg=self.COLORS["panel"]
        )

        tk.Label(
            self.distance_frame,
            text="Distance",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Sans", 9, "bold")
        ).pack(
            side="left",
            padx=(0, 8)
        )

        self.distance_var = tk.StringVar()

        self.distance_entry = ttk.Entry(
            self.distance_frame,
            textvariable=self.distance_var,
            style="Dark.TEntry",
            width=10
        )
        self.distance_entry.pack(
            side="left"
        )

        tk.Label(
            self.distance_frame,
            text="cm",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Sans", 9)
        ).pack(
            side="left",
            padx=(6, 10)
        )

        self.distance_button = ttk.Button(
            self.distance_frame,
            text="Submit",
            command=self.submit_distance,
            style="Accent.TButton"
        )
        self.distance_button.pack(
            side="left"
        )

        # ---------- lower two-column area ----------
        lower = tk.PanedWindow(
            shell,
            orient="horizontal",
            sashwidth=7,
            sashrelief="flat",
            bg=self.COLORS["bg"],
            bd=0
        )
        lower.pack(
            fill="both",
            expand=True
        )

        # left column
        left = tk.Frame(
            lower,
            bg=self.COLORS["panel"],
            highlightbackground=self.COLORS["border"],
            highlightthickness=1
        )

        preview_header = tk.Frame(
            left,
            bg=self.COLORS["panel"],
            padx=16,
            pady=12
        )
        preview_header.pack(
            fill="x"
        )

        tk.Label(
            preview_header,
            text="Latest observation",
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            font=("Sans", 12, "bold")
        ).pack(
            side="left"
        )

        self.preview_meta_label = tk.Label(
            preview_header,
            text="No frame",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Sans", 9)
        )
        self.preview_meta_label.pack(
            side="right"
        )

        preview_body = tk.Frame(
            left,
            bg="#070A0E"
        )
        preview_body.pack(
            fill="both",
            expand=True,
            padx=14,
            pady=(0, 14)
        )

        self.preview_label = tk.Label(
            preview_body,
            text="No image captured yet.",
            bg="#070A0E",
            fg=self.COLORS["muted"],
            font=("Sans", 11)
        )
        self.preview_label.pack(
            fill="both",
            expand=True,
            padx=10,
            pady=10
        )

        # right column
        right = tk.Frame(
            lower,
            bg=self.COLORS["bg"]
        )

        memory_card = tk.Frame(
            right,
            bg=self.COLORS["panel"],
            highlightbackground=self.COLORS["border"],
            highlightthickness=1,
            padx=16,
            pady=14
        )
        memory_card.pack(
            fill="x",
            pady=(0, 12)
        )

        memory_top = tk.Frame(
            memory_card,
            bg=self.COLORS["panel"]
        )
        memory_top.pack(
            fill="x"
        )

        tk.Label(
            memory_top,
            text="Visual context sent to Qwen",
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            font=("Sans", 12, "bold")
        ).pack(
            side="left"
        )

        self.context_count_label = tk.Label(
            memory_top,
            text="0 / 4 images",
            bg=self.COLORS["panel"],
            fg=self.COLORS["accent"],
            font=("Sans", 10, "bold")
        )
        self.context_count_label.pack(
            side="right"
        )

        tk.Label(
            memory_card,
            text=(
                "These are the actual recent camera frames retained "
                "in the multimodal request."
            ),
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Sans", 9),
            justify="left"
        ).pack(
            anchor="w",
            pady=(4, 8)
        )

        self.context_text = tk.Text(
            memory_card,
            height=5,
            wrap="none",
            bg=self.COLORS["input"],
            fg=self.COLORS["text"],
            insertbackground=self.COLORS["text"],
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
            font=("Monospace", 9),
            state="disabled"
        )
        self.context_text.pack(
            fill="x"
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

        log_header = tk.Frame(
            log_card,
            bg=self.COLORS["panel"],
            padx=16,
            pady=12
        )
        log_header.pack(
            fill="x"
        )

        tk.Label(
            log_header,
            text="Mission log",
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            font=("Sans", 12, "bold")
        ).pack(
            side="left"
        )

        self.log_text = tk.Text(
            log_card,
            wrap="word",
            state="disabled",
            bg=self.COLORS["input"],
            fg="#D8E2EE",
            insertbackground=self.COLORS["text"],
            selectbackground="#2D5F8F",
            relief="flat",
            bd=0,
            padx=14,
            pady=12,
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

        # Initial visual-context display.
        self.update_context_display([])

    def update_context_display(self, context_messages):
        image_count = sum(
            1
            for message in context_messages
            if message.get("images")
        )

        retained_paths = self.observation_paths[
            -IMAGE_HISTORY_LIMIT:
        ]

        self.context_count_label.configure(
            text=(
                f"{image_count} / "
                f"{IMAGE_HISTORY_LIMIT} images"
            )
        )

        self.context_text.configure(
            state="normal"
        )
        self.context_text.delete(
            "1.0",
            "end"
        )

        if not retained_paths:
            self.context_text.insert(
                "end",
                "No camera frames have been sent yet."
            )
        else:
            start_number = (
                len(self.observation_paths)
                - len(retained_paths)
                + 1
            )

            for offset, path in enumerate(
                retained_paths
            ):
                number = start_number + offset
                marker = (
                    "  ← newest"
                    if offset == len(retained_paths) - 1
                    else ""
                )
                self.context_text.insert(
                    "end",
                    f"{number:02d}  {Path(path).name}{marker}\n"
                )

        self.context_text.configure(
            state="disabled"
        )


    def log(self, text):
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

    def reset(self):
        self.messages = []
        self.current_tool = None
        self.current_arguments = {}
        self.current_assistant_message = None
        self.step_count = 0
        self.must_observe_after_move = False
        self.observation_paths = []

        self.action_label.configure(
            text="Idle",
            fg=self.COLORS["text"]
        )
        self.detail_label.configure(
            text="Press Start Mission when the scene is ready."
        )
        self.action_button.configure(
            text="",
            state="disabled"
        )
        self.distance_frame.pack_forget()
        self.start_button.configure(
            state="normal"
        )

        self.log_text.configure(
            state="normal"
        )
        self.log_text.delete(
            "1.0",
            "end"
        )
        self.log_text.configure(
            state="disabled"
        )

        self.preview_label.configure(
            image="",
            text="No image captured yet."
        )
        self.preview_label.image = None

        self.preview_meta_label.configure(
            text="No frame"
        )

        self.step_label.configure(
            text=f"Decision 0 / {MAX_STEPS}"
        )

        self.header_status_label.configure(
            text="●  IDLE",
            fg=self.COLORS["muted"]
        )

        self.update_context_display([])

    def start_mission(self):
        goal = self.goal_var.get().strip()

        if not goal:
            messagebox.showerror(
                "Missing goal",
                "Enter a mission goal."
            )
            return

        self.reset()

        self.start_button.configure(
            state="disabled"
        )

        self.messages = [
            {
                "role": "system",
                "content": ROBOT_POLICY
            },
            {
                "role": "user",
                "content": goal
            }
        ]

        self.log(
            f"USER: {goal}"
        )

        self.request_model_decision()

    def request_model_decision(self):
        if self.step_count >= MAX_STEPS:
            self.stop_with_error(
                f"Maximum step count ({MAX_STEPS}) reached."
            )
            return

        self.step_count += 1

        self.current_tool = None
        self.current_arguments = {}
        self.current_assistant_message = None

        self.action_label.configure(
            text="Qwen is deciding...",
            fg=self.COLORS["text"]
        )
        self.detail_label.configure(
            text=f"Decision {self.step_count}"
        )
        self.action_button.configure(
            state="disabled"
        )
        self.distance_frame.pack_forget()

        messages_copy = compact_old_images(
            self.messages
        )

        image_count = sum(
            1
            for message in messages_copy
            if message.get("images")
        )

        self.update_context_display(
            messages_copy
        )

        retained_paths = self.observation_paths[
            -IMAGE_HISTORY_LIMIT:
        ]

        self.log(
            f"CONTEXT: sending {image_count} camera image(s) to Qwen"
        )

        for path in retained_paths:
            self.log(
                f"  IMAGE: {Path(path).name}"
            )

        self.step_label.configure(
            text=f"Decision {self.step_count} / {MAX_STEPS}"
        )
        self.header_status_label.configure(
            text="●  THINKING",
            fg=self.COLORS["accent"]
        )

        threading.Thread(
            target=self.model_worker,
            args=(messages_copy,),
            daemon=True
        ).start()

    def model_worker(self, messages):
        try:
            payload = {
                "model": MODEL,
                "messages": messages,
                "tools": TOOLS,
                "think": False,
                "stream": False,
                "options": {
                    "temperature": 0
                }
            }

            request_data = json.dumps(
                payload
            ).encode("utf-8")

            request = urllib.request.Request(
                OLLAMA_URL,
                data=request_data,
                headers={
                    "Content-Type": "application/json"
                },
                method="POST"
            )

            start = time.perf_counter()

            with urllib.request.urlopen(
                request,
                timeout=120
            ) as response:
                result = json.loads(
                    response.read()
                )

            latency_ms = (
                time.perf_counter() - start
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
                self.worker_queue.put(
                    {
                        "type": "error",
                        "message": (
                            "Model returned no tool call.\n\n"
                            + json.dumps(
                                message,
                                indent=2
                            )
                        )
                    }
                )
                return

            function = tool_calls[0].get(
                "function",
                {}
            )

            self.worker_queue.put(
                {
                    "type": "model",
                    "tool": function.get(
                        "name"
                    ),
                    "arguments": function.get(
                        "arguments",
                        {}
                    ),
                    "assistant_message": message,
                    "latency_ms": latency_ms
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
                f"HTTP Error {exc.code}: {exc.reason}"
            )

            if body:
                message += (
                    "\n\nOllama response:\n"
                    + body
                )

            self.worker_queue.put(
                {
                    "type": "error",
                    "message": message
                }
            )

        except Exception as exc:
            self.worker_queue.put(
                {
                    "type": "error",
                    "message": str(exc)
                }
            )

    def poll_worker_queue(self):
        try:
            item = self.worker_queue.get_nowait()
        except queue.Empty:
            self.root.after(
                100,
                self.poll_worker_queue
            )
            return

        if item["type"] == "model":
            self.handle_model_decision(
                item
            )

        elif item["type"] == "capture":
            self.finish_capture(
                item["image_path"]
            )

        elif item["type"] == "error":
            self.stop_with_error(
                item["message"]
            )

        self.root.after(
            100,
            self.poll_worker_queue
        )

    def handle_model_decision(self, item):
        tool = item["tool"]
        args = item["arguments"]

        self.current_tool = tool
        self.current_arguments = args
        self.current_assistant_message = (
            item["assistant_message"]
        )

        if (
            self.must_observe_after_move
            and tool != "observe"
        ):
            self.log(
                f"SAFETY: rejected {tool}{args}; "
                "fresh observation required after movement."
            )

            self.messages.append(
                {
                    "role": "user",
                    "content": (
                        "Safety controller rejected that action. "
                        "The robot moved since the last camera frame, "
                        "so call observe() now before any other "
                        "navigation action."
                    )
                }
            )

            self.request_model_decision()
            return

        self.log(
            f"AI: {tool}{args} "
            f"({item['latency_ms']:.1f} ms)"
        )

        self.header_status_label.configure(
            text="●  AWAITING YOU",
            fg=self.COLORS["warning"]
        )

        self.root.bell()

        if tool == "observe":
            self.action_label.configure(
                text="OBSERVE"
            )
            self.detail_label.configure(
                text=(
                    "Point the webcam where the robot would "
                    "currently be looking, then capture."
                )
            )
            self.action_button.configure(
                text="Capture Observation",
                state="normal"
            )
            return

        if tool == "turn_left":
            angle = args.get(
                "angle_degrees",
                "?"
            )
            self.action_label.configure(
                text=f"TURN LEFT {angle}°"
            )
            self.detail_label.configure(
                text=(
                    f"Rotate the webcam approximately {angle}° "
                    f"to the LEFT, then confirm."
                )
            )
            self.action_button.configure(
                text="Movement Complete",
                state="normal"
            )
            return

        if tool == "turn_right":
            angle = args.get(
                "angle_degrees",
                "?"
            )
            self.action_label.configure(
                text=f"TURN RIGHT {angle}°"
            )
            self.detail_label.configure(
                text=(
                    f"Rotate the webcam approximately {angle}° "
                    f"to the RIGHT, then confirm."
                )
            )
            self.action_button.configure(
                text="Movement Complete",
                state="normal"
            )
            return

        if tool == "move_forward":
            distance = args.get(
                "distance_cm",
                "?"
            )

            self.action_label.configure(
                text=f"MOVE FORWARD {distance} cm"
            )
            self.detail_label.configure(
                text=(
                    f"Move the webcam approximately {distance} cm "
                    f"FORWARD, then confirm."
                )
            )
            self.action_button.configure(
                text="Movement Complete",
                state="normal"
            )
            return

        if tool == "get_distance":
            self.action_label.configure(
                text="MEASURE DISTANCE"
            )
            self.detail_label.configure(
                text=(
                    "Measure or estimate the distance directly "
                    "ahead to the target and enter it below."
                )
            )

            self.distance_var.set("")
            self.distance_frame.pack(
                anchor="w"
            )
            self.distance_entry.focus_set()
            return

        if tool == "stop":
            self.messages.append(
                self.current_assistant_message
            )

            self.action_label.configure(
                text="MISSION COMPLETE",
                fg=self.COLORS["success"]
            )
            self.detail_label.configure(
                text="Qwen called stop()."
            )
            self.header_status_label.configure(
                text="●  COMPLETE",
                fg=self.COLORS["success"]
            )
            self.action_button.configure(
                state="disabled"
            )

            self.log(
                "MISSION COMPLETE: stop()"
            )

            self.root.bell()

            messagebox.showinfo(
                "Mission complete",
                "Qwen called stop()."
            )
            return

        self.stop_with_error(
            f"Unknown tool requested: {tool}"
        )

    def handle_action_button(self):
        if self.current_tool == "observe":
            self.capture_observation()
            return

        if self.current_tool in [
            "turn_left",
            "turn_right",
            "move_forward"
        ]:
            self.complete_movement()
            return

    def capture_observation(self):
        self.action_button.configure(
            state="disabled"
        )
        self.action_label.configure(
            text="Capturing..."
        )

        threading.Thread(
            target=self.capture_worker,
            daemon=True
        ).start()

    def capture_worker(self):
        try:
            timestamp = int(
                time.time() * 1000
            )

            image_path = (
                CAPTURE_DIR
                / f"observation_{timestamp}.png"
            )

            camera = (
                self.camera_var.get().strip()
            )

            command = [
                "ffmpeg",
                "-loglevel",
                "error",
                "-f",
                "v4l2",
                "-i",
                camera,
                "-frames:v",
                "1",
                "-update",
                "1",
                "-y",
                str(image_path)
            ]

            subprocess.run(
                command,
                check=True,
                timeout=15
            )

            self.worker_queue.put(
                {
                    "type": "capture",
                    "image_path": str(
                        image_path
                    )
                }
            )

        except Exception as exc:
            self.worker_queue.put(
                {
                    "type": "error",
                    "message": (
                        "Camera capture failed: "
                        + str(exc)
                    )
                }
            )

    def finish_capture(self, image_path):
        self.show_preview(
            image_path
        )

        self.observation_paths.append(
            image_path
        )

        self.messages.append(
            self.current_assistant_message
        )

        self.messages.append(
            {
                "role": "tool",
                "tool_name": "observe",
                "content": (
                    f"Current camera observation: "
                    f"{Path(image_path).name}"
                ),
                "images": [
                    encode_image(
                        image_path
                    )
                ]
            }
        )

        self.log(
            f"TOOL: observe() -> {image_path}"
        )

        self.must_observe_after_move = False

        self.request_model_decision()

    def show_preview(self, image_path):
        try:
            photo = tk.PhotoImage(
                file=image_path
            )

            max_width = 760
            max_height = 520

            x_scale = max(
                1,
                photo.width()
                // max_width
            )

            y_scale = max(
                1,
                photo.height()
                // max_height
            )

            scale = max(
                x_scale,
                y_scale
            )

            if scale > 1:
                photo = photo.subsample(
                    scale,
                    scale
                )

            self.preview_label.configure(
                image=photo,
                text=""
            )
            self.preview_label.image = photo

            self.preview_meta_label.configure(
                text=Path(image_path).name
            )

        except Exception as exc:
            self.preview_label.configure(
                text=(
                    f"Captured:\n{image_path}\n\n"
                    f"Preview unavailable:\n{exc}"
                ),
                image=""
            )

    def complete_movement(self):
        tool = self.current_tool
        args = self.current_arguments

        self.messages.append(
            self.current_assistant_message
        )

        if tool == "turn_left":
            value = args.get(
                "angle_degrees"
            )
            result = (
                f"Turn left by {value} degrees completed."
            )

        elif tool == "turn_right":
            value = args.get(
                "angle_degrees"
            )
            result = (
                f"Turn right by {value} degrees completed."
            )

        elif tool == "move_forward":
            distance = args.get(
                "distance_cm"
            )

            result = (
                f"Forward movement of {distance} cm completed."
            )

            self.must_observe_after_move = True

        else:
            self.stop_with_error(
                "Unexpected movement tool."
            )
            return

        self.messages.append(
            {
                "role": "tool",
                "tool_name": tool,
                "content": result
            }
        )

        self.log(
            f"TOOL: {result}"
        )

        self.request_model_decision()

    def submit_distance(self):
        raw = self.distance_var.get().strip()

        try:
            distance = float(
                raw
            )
        except ValueError:
            messagebox.showerror(
                "Invalid distance",
                "Enter a number such as 82 or 5.5."
            )
            return

        if distance < 0:
            messagebox.showerror(
                "Invalid distance",
                "Distance cannot be negative."
            )
            return

        self.messages.append(
            self.current_assistant_message
        )

        result = (
            f"Ultrasonic distance is "
            f"{distance:.1f} cm."
        )

        self.messages.append(
            {
                "role": "tool",
                "tool_name": "get_distance",
                "content": result
            }
        )

        self.log(
            f"TOOL: {result}"
        )

        self.distance_frame.pack_forget()

        self.request_model_decision()

    def stop_with_error(self, message):
        self.current_tool = None

        self.action_label.configure(
            text="TEST STOPPED",
            fg=self.COLORS["danger"]
        )
        self.header_status_label.configure(
            text="●  STOPPED",
            fg=self.COLORS["danger"]
        )
        self.detail_label.configure(
            text=message
        )
        self.action_button.configure(
            state="disabled"
        )
        self.distance_frame.pack_forget()
        self.start_button.configure(
            state="normal"
        )

        self.log(
            f"ERROR: {message}"
        )

        messagebox.showerror(
            "Test stopped",
            message
        )


def main():
    root = tk.Tk()
    HumanRobotGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
