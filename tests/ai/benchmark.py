#!/usr/bin/env python3

import json
import time
import urllib.request


OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3.5:9b"

GOAL_DISTANCE_CM = 5.0
ANGLE_TOLERANCE_DEG = 5.0
DISTANCE_TOLERANCE_CM = 2.0
MAX_STEPS = 12


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "observe",
            "description": "Observe the current scene using the robot camera.",
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
            "description": "Get ultrasonic distance directly ahead in centimeters.",
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
            "description":
                "Move the robot straight forward by the requested "
                "distance in centimeters.",
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
            "description":
                "Turn the robot left/counter-clockwise by the "
                "requested number of degrees.",
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
            "description":
                "Turn the robot right/clockwise by the "
                "requested number of degrees.",
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
            "description":
                "Stop the robot when the requested destination "
                "or stopping distance has been reached.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


def call_model(messages):
    payload = {
        "model": MODEL,
        "messages": messages,
        "tools": TOOLS,
        "stream": False,
        "options": {
            "temperature": 0
        }
    }

    payload_bytes = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        OLLAMA_URL,
        data=payload_bytes,
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
    )

    start_time = time.perf_counter()

    with urllib.request.urlopen(request) as response:
        response_body = response.read()
        result = json.loads(response_body)

    wall_ms = (time.perf_counter() - start_time) * 1000.0

    return result, wall_ms


def get_tool_call(response):
    tool_calls = response["message"].get("tool_calls", [])

    if not tool_calls:
        return None, {}

    function = tool_calls[0]["function"]

    return function["name"], function.get("arguments", {})


# ============================================================
# PHASE 1
# Single-step correctness
# ============================================================

def validate_arguments(expected_tool, expected_value, arguments):
    if expected_tool in ["observe", "get_distance", "stop"]:
        return arguments == {}

    if expected_tool in ["turn_left", "turn_right"]:
        actual_angle = arguments.get("angle_degrees")

        if actual_angle is None:
            return False

        return abs(float(actual_angle) - expected_value) <= 5.0

    if expected_tool == "move_forward":
        actual_distance = arguments.get("distance_cm")

        if actual_distance is None:
            return False

        return abs(float(actual_distance) - expected_value) <= 10.0

    return False


def run_single_test(
    name,
    observation,
    expected_tool,
    expected_value=None
):
    messages = [
        {
            "role": "user",
            "content":
                "Go in front of the dustbin and stop about "
                "5 cm away."
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "observe",
                        "arguments": {}
                    }
                }
            ]
        },
        {
            "role": "tool",
            "tool_name": "observe",
            "content": observation
        }
    ]

    response, wall_ms = call_model(messages)

    actual_tool, arguments = get_tool_call(response)

    tool_ok = actual_tool == expected_tool

    args_ok = False
    if tool_ok:
        args_ok = validate_arguments(
            expected_tool,
            expected_value,
            arguments
        )

    passed = tool_ok and args_ok

    print()
    print("=" * 60)
    print(name)
    print("=" * 60)
    print(f"Observation    : {observation}")
    print(f"Expected tool  : {expected_tool}")
    print(f"Expected value : {expected_value}")
    print(f"Actual tool    : {actual_tool}")
    print(f"Arguments      : {arguments}")
    print(f"Tool correct   : {'YES' if tool_ok else 'NO'}")
    print(f"Args correct   : {'YES' if args_ok else 'NO'}")
    print(f"Latency        : {wall_ms:.1f} ms")
    print(f"Result         : {'PASS' if passed else 'FAIL'}")

    return passed, wall_ms


def run_phase_1():
    tests = [
        (
            "Right 10 degrees",
            "The dustbin is visible 10 degrees to the right.",
            "turn_right",
            10
        ),
        (
            "Right 30 degrees",
            "The dustbin is visible 30 degrees to the right.",
            "turn_right",
            30
        ),
        (
            "Right 70 degrees",
            "The dustbin is visible 70 degrees to the right.",
            "turn_right",
            70
        ),

        (
            "Left 10 degrees",
            "The dustbin is visible 10 degrees to the left.",
            "turn_left",
            10
        ),
        (
            "Left 30 degrees",
            "The dustbin is visible 30 degrees to the left.",
            "turn_left",
            30
        ),
        (
            "Left 70 degrees",
            "The dustbin is visible 70 degrees to the left.",
            "turn_left",
            70
        ),

        (
            "Centered, distance unknown",
            "The dustbin is centered directly ahead. "
            "Distance is unknown.",
            "get_distance",
            None
        ),

        (
            "Centered, 200 cm",
            "The dustbin is centered directly ahead. "
            "Ultrasonic distance is 200 cm.",
            "move_forward",
            195
        ),

        (
            "Centered, 100 cm",
            "The dustbin is centered directly ahead. "
            "Ultrasonic distance is 100 cm.",
            "move_forward",
            95
        ),

        (
            "Centered, 25 cm",
            "The dustbin is centered directly ahead. "
            "Ultrasonic distance is 25 cm.",
            "move_forward",
            20
        ),

        (
            "At target distance",
            "The dustbin is centered directly ahead. "
            "Ultrasonic distance is 5 cm.",
            "stop",
            None
        )
    ]

    passed_count = 0
    latencies = []

    for name, observation, expected_tool, expected_value in tests:
        passed, wall_ms = run_single_test(
            name,
            observation,
            expected_tool,
            expected_value
        )

        latencies.append(wall_ms)

        if passed:
            passed_count += 1

    print()
    print("#" * 60)
    print("PHASE 1 RESULTS")
    print("#" * 60)
    print(f"Passed          : {passed_count} / {len(tests)}")
    print(
        f"Average latency : "
        f"{sum(latencies) / len(latencies):.1f} ms"
    )
    print(
        f"Worst latency   : "
        f"{max(latencies):.1f} ms"
    )


# ============================================================
# PHASE 2
# Multi-step simulated missions
# ============================================================

class FakeRobotWorld:
    def __init__(self, target_angle_deg, distance_cm):
        self.target_angle_deg = float(target_angle_deg)
        self.distance_cm = float(distance_cm)

    def describe_scene(self):
        if abs(self.target_angle_deg) <= ANGLE_TOLERANCE_DEG:
            direction = "centered directly ahead"

        elif self.target_angle_deg > 0:
            direction = (
                f"{abs(self.target_angle_deg):.1f} "
                "degrees to the right"
            )

        else:
            direction = (
                f"{abs(self.target_angle_deg):.1f} "
                "degrees to the left"
            )

        return (
            f"The dustbin is {direction}. "
            f"Ultrasonic distance is "
            f"{self.distance_cm:.1f} cm."
        )

    def execute(self, tool_name, arguments):
        if tool_name == "observe":
            return self.describe_scene()

        if tool_name == "get_distance":
            return (
                f"Ultrasonic distance is "
                f"{self.distance_cm:.1f} cm."
            )

        if tool_name == "turn_right":
            angle = float(arguments["angle_degrees"])

            self.target_angle_deg -= angle

            return (
                f"Turn right completed. "
                f"{self.describe_scene()}"
            )

        if tool_name == "turn_left":
            angle = float(arguments["angle_degrees"])

            self.target_angle_deg += angle

            return (
                f"Turn left completed. "
                f"{self.describe_scene()}"
            )

        if tool_name == "move_forward":
            distance = float(arguments["distance_cm"])

            self.distance_cm -= distance

            return (
                f"Forward movement completed. "
                f"{self.describe_scene()}"
            )

        if tool_name == "stop":
            return "Robot stopped."

        return f"ERROR: Unknown tool: {tool_name}"


def mission_successful(world):
    angle_ok = (
        abs(world.target_angle_deg)
        <= ANGLE_TOLERANCE_DEG
    )

    distance_ok = (
        abs(world.distance_cm - GOAL_DISTANCE_CM)
        <= DISTANCE_TOLERANCE_CM
    )

    return angle_ok and distance_ok


def run_episode(
    name,
    start_angle,
    start_distance
):
    print()
    print("=" * 70)
    print(f"EPISODE: {name}")
    print("=" * 70)

    world = FakeRobotWorld(
        target_angle_deg=start_angle,
        distance_cm=start_distance
    )

    messages = [
        {
            "role": "user",
            "content":
                "Go in front of the dustbin and stop about "
                "5 cm away."
        }
    ]

    total_latency_ms = 0.0

    print(
        f"Initial world: "
        f"angle={world.target_angle_deg:.1f}°, "
        f"distance={world.distance_cm:.1f} cm"
    )

    for step in range(1, MAX_STEPS + 1):
        response, wall_ms = call_model(messages)

        total_latency_ms += wall_ms

        tool_name, arguments = get_tool_call(response)

        print()
        print(f"Step {step}")
        print(f"  Tool      : {tool_name}")
        print(f"  Arguments : {arguments}")
        print(f"  Latency   : {wall_ms:.1f} ms")

        if tool_name is None:
            print(
                "  FAIL: model returned no tool call"
            )

            return False, total_latency_ms, step

        #
        # Validate movement before executing it.
        #
        if tool_name == "move_forward":
            distance = arguments.get("distance_cm")

            if distance is None:
                print(
                    "  FAIL: move_forward missing "
                    "distance_cm"
                )

                return False, total_latency_ms, step

            distance = float(distance)

            if distance <= 0:
                print(
                    "  FAIL: forward distance must be "
                    "positive"
                )

                return False, total_latency_ms, step

            if distance > world.distance_cm:
                print(
                    "  FAIL: requested movement would "
                    "move past the target"
                )

                return False, total_latency_ms, step

        #
        # Validate turn command.
        #
        if tool_name in [
            "turn_left",
            "turn_right"
        ]:
            angle = arguments.get("angle_degrees")

            if angle is None:
                print(
                    "  FAIL: turn missing "
                    "angle_degrees"
                )

                return False, total_latency_ms, step

            angle = float(angle)

            if angle <= 0:
                print(
                    "  FAIL: turn angle must be positive"
                )

                return False, total_latency_ms, step

        #
        # Add model's tool call to conversation history.
        #
        messages.append(
            response["message"]
        )

        #
        # Execute tool in fake environment.
        #
        tool_result = world.execute(
            tool_name,
            arguments
        )

        print(
            f"  Tool result: {tool_result}"
        )

        print(
            f"  World state: "
            f"angle={world.target_angle_deg:.1f}°, "
            f"distance={world.distance_cm:.1f} cm"
        )

        #
        # Add tool result to conversation history.
        #
        messages.append(
            {
                "role": "tool",
                "tool_name": tool_name,
                "content": tool_result
            }
        )

        #
        # If model decided to stop, determine whether
        # it actually completed the mission.
        #
        if tool_name == "stop":
            passed = mission_successful(world)

            print()

            if passed:
                print("EPISODE RESULT: PASS")

            else:
                print("EPISODE RESULT: FAIL")
                print(
                    "Model stopped, but robot was not "
                    "at the required goal."
                )

            return (
                passed,
                total_latency_ms,
                step
            )

    print()
    print("EPISODE RESULT: FAIL")
    print(
        "Reason: maximum number of steps reached"
    )

    return (
        False,
        total_latency_ms,
        MAX_STEPS
    )


def run_phase_2():
    episodes = [
        (
            "Target far right and far away",
            40,
            150
        ),

        (
            "Target far left and far away",
            -60,
            120
        ),

        (
            "Target slightly right",
            10,
            80
        ),

        (
            "Target slightly left",
            -15,
            50
        ),

        (
            "Already centered but far",
            0,
            100
        ),

        (
            "Centered and close",
            0,
            25
        ),

        (
            "Already at goal",
            0,
            5
        )
    ]

    passed_count = 0
    mission_latencies = []
    mission_steps = []

    for name, angle, distance in episodes:
        passed, latency_ms, steps = run_episode(
            name,
            angle,
            distance
        )

        mission_latencies.append(
            latency_ms
        )

        mission_steps.append(
            steps
        )

        if passed:
            passed_count += 1

    print()
    print("#" * 70)
    print("PHASE 2 RESULTS")
    print("#" * 70)

    print(
        f"Passed                 : "
        f"{passed_count} / {len(episodes)}"
    )

    print(
        f"Average mission latency: "
        f"{sum(mission_latencies) / len(mission_latencies):.1f} ms"
    )

    print(
        f"Average steps          : "
        f"{sum(mission_steps) / len(mission_steps):.1f}"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    run_phase_1()
    run_phase_2()
