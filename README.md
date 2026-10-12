# Vision-Language AI Robot

An Embedded Linux robotic platform that uses a locally running vision-language AI model for closed-loop autonomous navigation.

The robot uses a **Raspberry Pi** for camera capture, ultrasonic sensing and motor control, while a **Linux PC** runs the vision-language model. Camera observations and robot commands are exchanged over Wi-Fi.

The goal of the project is to explore autonomous robot navigation using **direct AI motion decisions rather than traditional SLAM or path-planning algorithms**.

## Demo

**Task:** Find the pink bottle and stop 5 cm away from it.

![Robot Demo](docs/robot_demo.gif)

## System Architecture

```text
                         Wi-Fi
┌──────────────────────┐       ┌──────────────────────────┐
│    Raspberry Pi      │──────▶│        Linux PC          │
│                      │ Image │                          │
│  Camera              │       │  Ollama                  │
│  Ultrasonic Sensor   │       │  Qwen3.5 9B             │
│  Motor Control       │◀──────│  Navigation Loop         │
│                      │ Cmd   │                          │
└──────────────────────┘       └──────────────────────────┘
          │
          ▼
      DC Motors
```

The Raspberry Pi exposes the physical robot capabilities over the network. The Linux host receives camera observations, runs the vision-language model, and sends the selected motion command back to the robot.

This creates a closed loop:

```text
Observe → AI Decision → Robot Primitive → Physical Movement → Observe
```

## Robot Primitives

The AI does not directly control GPIO or motor timing. It selects from a small set of robot primitives:

```text
observe()
get_distance()
move_forward(distance_cm)
turn_left(angle_degrees)
turn_right(angle_degrees)
stop()
```

The surrounding software executes the selected primitive and returns the result to the model for the next decision.

## Navigation Approach

The current system intentionally does not use a traditional SLAM or path-planning stack.

Instead, the vision-language model receives the navigation goal and camera observations, then selects the next robot primitive. After physical movement, the robot observes the environment again and repeats the process.

Ultrasonic sensing provides direct distance measurements when approaching the target.

## Hardware

- Raspberry Pi
- Camera
- Ultrasonic distance sensor
- Tracked DC motor platform
- Motor controller
- 2× 18650 battery power system

## Software

- Raspberry Pi OS / Embedded Linux
- Python
- Ollama
- Qwen3.5 9B vision-language model
- HTTP/JSON communication
- Wi-Fi networking

## AI Model Evaluation

Before connecting the model to the physical robot, the AI navigation approach was tested independently across:

- single-step motion decisions
- multi-step simulated missions
- prompt wording variations
- real-image visual reasoning
- image-to-robot-primitive decisions
- Qwen3.5 4B vs 9B model comparison

The evaluation showed that **Qwen3.5 9B** was substantially more reliable for spatial reasoning and multi-step navigation than the tested 4B model.

See the full experiments, benchmark results and design reasoning here:

**[AI Model Evaluation](tests/ai/README.md)**

## Project Status

The current prototype demonstrates the complete physical loop:

```text
Human Goal
    ↓
Vision-Language AI
    ↓
Robot Primitive
    ↓
Wi-Fi
    ↓
Raspberry Pi
    ↓
Motors / Sensors
    ↓
New Camera Observation
    ↓
Vision-Language AI
```

Current work focuses on improving real-world navigation behavior, reducing model-loop latency and making physical motion more robust.
