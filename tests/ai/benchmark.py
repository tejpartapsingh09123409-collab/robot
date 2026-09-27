#!/usr/bin/env python3

import json
import time
import urllib.request


OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3.5:9b"


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
            "description": "Move the robot straight forward by the requested distance in centimeters.",
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
            "description": "Turn the robot left/counter-clockwise by the requested number of degrees.",
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
            "description": "Turn the robot right/clockwise by the requested number of degrees.",
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
            "description": "Stop the robot when the requested destination or stopping distance has been reached.",
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


def validate_arguments(expected_tool, expected_value, arguments):
    if expected_tool in ["observe", "get_distance", "stop"]:
        return arguments == {}

    if expected_tool in ["turn_left", "turn_right"]:
        actual_angle = arguments.get("angle_degrees")

        if actual_angle is None:
            return False

        return abs(actual_angle - expected_value) <= 5

    if expected_tool == "move_forward":
        actual_distance = arguments.get("distance_cm")

        if actual_distance is None:
            return False

        return abs(actual_distance - expected_value) <= 10

    return False


def run_test(name, observation, expected_tool, expected_value=None):
    messages = [
        {
            "role": "user",
            "content": "Go in front of the dustbin and stop about 5 cm away."
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
            "The dustbin is centered directly ahead. Distance is unknown.",
            "get_distance",
            None
        ),
        (
            "Centered, 200 cm",
            "The dustbin is centered directly ahead. Ultrasonic distance is 200 cm.",
            "move_forward",
            195
        ),
        (
            "Centered, 100 cm",
            "The dustbin is centered directly ahead. Ultrasonic distance is 100 cm.",
            "move_forward",
            95
        ),
        (
            "Centered, 25 cm",
            "The dustbin is centered directly ahead. Ultrasonic distance is 25 cm.",
            "move_forward",
            20
        ),
        (
            "At target distance",
            "The dustbin is centered directly ahead. Ultrasonic distance is 5 cm.",
            "stop",
            None
        )
    ]

    passed_count = 0
    latencies = []

    for name, observation, expected_tool, expected_value in tests:
        passed, wall_ms = run_test(
            name,
            observation,
            expected_tool,
            expected_value
        )

        latencies.append(wall_ms)

        if passed:
            passed_count += 1

    avg_latency = sum(latencies) / len(latencies)
    worst_latency = max(latencies)

    print()
    print("#" * 60)
    print("PHASE 1 RESULTS")
    print("#" * 60)
    print(f"Passed          : {passed_count} / {len(tests)}")
    print(f"Average latency : {avg_latency:.1f} ms")
    print(f"Worst latency   : {worst_latency:.1f} ms")


if __name__ == "__main__":
    run_phase_1()
