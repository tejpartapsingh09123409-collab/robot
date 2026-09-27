# AI Model Evaluation for Milestone 1

## Goal

Determine whether a local AI model can act as the high-level intelligence for Milestone 1:

> Go in front of the requested object and stop at the requested distance.

The AI is expected to translate a high-level human goal into a sequence of robot primitives while using observations returned by the robot.

## Candidate setup

- Runtime: Ollama
- Model: Qwen3.5 9B
- Hardware: Lenovo Legion with RTX 5050 Laptop GPU, approximately 7.5 GiB usable VRAM reported by Ollama
- Interface: HTTP/JSON through Ollama's local API
- Sampling: temperature 0 for deterministic evaluation

## Primitive interface

The model was given these tools:

- `observe()`
- `get_distance()`
- `move_forward(distance_cm)`
- `turn_left(angle_degrees)`
- `turn_right(angle_degrees)`
- `stop()`

The surrounding application sends the full conversation history on each model call, along with the tool definitions. Tool results are appended to the history before the next model call.

## Phase 1 — Single-step decision correctness

Purpose: verify that the model chooses the correct primitive and produces a sensible argument for a known observation.

Examples included:

- target 10°, 30°, and 70° to the right
- target 10°, 30°, and 70° to the left
- target centered with unknown distance
- target centered at 200 cm, 100 cm, and 25 cm
- target centered at the 5 cm goal distance

### Result

- Passed: 11 / 11
- Average latency: 2721.1 ms
- Worst latency: 8888.9 ms

The model correctly selected the expected primitives and produced sensible arguments. For example:

- 30° right → `turn_right(30)`
- 70° left → `turn_left(70)`
- distance unknown → `get_distance()`
- 100 cm away with a 5 cm goal → `move_forward(95)`
- 5 cm away → `stop()`

## Phase 2 — Multi-step simulated missions

Purpose: verify that the model can maintain the original goal across multiple tool calls and complete an entire mission.

A simple Python fake world tracked:

- target angle relative to the robot
- target distance

After each tool call, the fake world updated its state and returned the result to the model. The full history was then sent again for the next decision.

Example episode:

1. Start: target 40° right, 150 cm away
2. Model: `observe()`
3. Observation: target 40° right, 150 cm away
4. Model: `turn_right(40)`
5. World becomes centered
6. Model: `move_forward(145)`
7. World becomes 5 cm away
8. Model: `stop()`

### Result

- Passed: 7 / 7 missions
- Average mission latency: 8841.9 ms
- Average steps: 3.6

Tested starts included far right, far left, slight offsets, already centered, close to the target, and already at the goal.

## Phase 3 — Wording robustness

Purpose: verify that the model is responding to meaning rather than memorizing one specific sentence format.

The same physical situations were described using different wording, including:

- `Go in front of the dustbin...`
- `Drive over to the trash can...`
- `Position yourself in front of the garbage bin...`
- `Approach the target...`

Observations were also varied, for example:

- `The dustbin is 30 degrees to the right.`
- `The trash can is off to your right by roughly 30 degrees.`
- `Target bearing is +30 degrees, where positive means right.`

### Result

- Passed: 22 / 23
- Success rate: 95.7%
- Average latency: 1989.2 ms
- Worst latency: 5726.3 ms

The one failing test still selected the correct primitive but chose a conservative partial movement:

- Goal: final range 5 cm
- Current range: 100 cm
- Expected benchmark value: `move_forward(95)`
- Actual: `move_forward(50)`

This may not represent a true intelligence failure because a closed-loop robot could move partially, observe again, and continue.

## Current conclusion

Qwen3.5 9B running locally through Ollama is good enough to continue with for Milestone 1.

Evidence so far shows that it can:

- understand the high-level goal
- select structured robot primitives
- produce sensible tool arguments
- maintain context across multiple steps
- react to tool results
- complete simulated missions
- generalize across varied wording

The main weakness observed so far is latency. Typical calls are often around 1.5–2.5 seconds, with occasional larger spikes.

## Remaining intelligence test

The major unproven part is real vision.

So far, camera information has been simulated as text such as:

`The dustbin is 30 degrees to the right.`

The next test should provide actual camera images to the multimodal model and evaluate whether it can identify the requested object and choose a sensible next primitive.

Once that works sufficiently well, the intelligence investigation should stop expanding and the project should move into the C++/Linux robot integration.
