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

## Phase 4 — Real-image vision

Purpose: verify that Qwen3.5 9B can consume an actual camera image rather than a text description of the scene.

Three local webcam images were captured with the same dustbin placed on the left, center, and right of the image. The model was asked to identify the dustbin and classify its coarse horizontal position.

### Result

- Passed: 3 / 3
- Average latency: 9172.2 ms
- Worst latency: 12055.4 ms

The model correctly identified all three positions:

- left image → `LEFT`
- center image → `CENTER`
- right image → `RIGHT`

This established that the local multimodal path works end to end:

`JPEG image → Ollama → Qwen3.5 9B vision → spatial interpretation`

The vision calls were considerably slower than the earlier text-only calls, so image inference latency remains an important system consideration.

## Phase 5 — Real image to robot primitive

Purpose: test the more relevant question for the robot: given a real-world image, the high-level goal, and the actual primitive interface, can the model choose a sensible next robot action?

A nine-image public test set was built from Open Images waste-container annotations:

- 3 images with the annotated container on the left
- 3 centered
- 3 on the right

The expected action was derived from the annotated horizontal location:

- left → `turn_left(...)`
- center → `get_distance()`
- right → `turn_right(...)`

The exact turn angle was not graded because an ordinary image annotation gives image position, not calibrated robot bearing.

The model was allowed to call `observe()` again when uncertain. When it did, the benchmark returned the same scene because no physical action had changed the world. A maximum of three decisions was allowed; repeated observation without progress would fail.

### Result

- Passed: 8 / 9
- Success rate: 88.9%
- Average total latency: 3405.4 ms
- Worst total latency: 8283.7 ms
- Average decisions used: 1.6

Observed behavior included:

- `observe() → turn_left(45)`
- `observe() → turn_right(15)`
- centered scenes → `get_distance()` directly

The single nominal failure was a large, nearby waste container whose annotated bounding-box center fell in the left third of the image. The model chose `get_distance()` instead of `turn_left(...)`. Manual inspection showed the object occupied a large part of the image and extended close to the camera center, so the case is ambiguous for the actual robotics question of whether the robot is sufficiently aligned to range the target. It is therefore recorded as a benchmark mismatch rather than strong evidence of a bad navigation decision.

The main conclusion from Phase 5 is that Qwen3.5 9B can usually combine real visual input, the high-level goal, and the robot tool interface to produce a sensible next primitive, including requesting another observation when uncertain.

## Current conclusion

Qwen3.5 9B running locally through Ollama is good enough to continue with for Milestone 1.

Evidence now shows that it can:

- understand the high-level goal
- select structured robot primitives
- produce sensible tool arguments
- maintain context across multiple steps
- react to tool results
- complete simulated missions
- generalize across varied wording
- interpret real camera images
- identify coarse target position from real images
- combine real visual input with the robot primitive interface
- request another observation when uncertain and then continue toward an action

The remaining uncertainty is no longer whether the basic AI approach works. The next uncertainty is system integration in the physical loop: camera capture, sensor feedback, primitive execution, state/history, safety checks, and behavior when the real world does not match the model's expectation.

Latency remains the clearest weakness. Text-only calls are often around 1.5–2.5 seconds, while vision calls can be several seconds and occasionally much longer. Fast continuous motion control should therefore remain deterministic rather than depending on a model call for every small correction.

The intelligence benchmark should stop expanding for now. The project should move into the real C++/Linux robot loop and return to model evaluation only when a concrete integration problem requires it.


## Model size comparison — Qwen3.5 4B vs 9B

After establishing the 9B baseline, the same three benchmark phases were repeated with Qwen3.5 4B to see whether the smaller model could reduce latency without sacrificing too much reliability.

The benchmark itself was kept unchanged so the comparison was fair: same tool definitions, same prompts, same fake-world logic, same temperature setting, and same machine.

### Qwen3.5 4B results

#### Phase 1 — Single-step decisions

- Passed: 3 / 11
- Average latency: 1924.4 ms
- Worst latency: 6102.0 ms

The main failure pattern was directional reasoning. The 4B model flipped left and right on all six basic direction tests. It also chose poor forward distances in some far-distance cases.

Examples:

- target 30° right → chose `turn_left(30)`
- target 30° left → chose `turn_right(30)`
- 200 cm away → chose `move_forward(100)` instead of approximately 195 cm
- 100 cm away → chose `move_forward(35)` instead of approximately 95 cm

#### Phase 2 — Multi-step missions

- Passed: 5 / 7 missions
- Average mission latency: 11101.2 ms
- Average steps: 5.4

Although individual 4B calls were often faster, the complete missions were slower on average because the model made more mistakes and required more actions.

In one failed mission, the target started 40° to the right. The model initially turned left, increasing the error, later drove forward while still badly misaligned, and eventually stopped at the correct distance while still approximately 80° away from the required heading.

This is a more important failure than merely choosing a conservative movement distance because it shows that the smaller model can make incorrect spatial decisions and continue acting on them.

#### Phase 3 — Wording robustness

- Passed: 17 / 23
- Success rate: 73.9%
- Average latency: 1476.1 ms
- Worst latency: 1888.2 ms

The 4B model was clearly faster in this phase, but its reliability dropped substantially compared with 9B. Failures included incorrect left/right decisions, moving when distance was unknown, and poor movement-distance choices.

### Comparison

| Metric | Qwen3.5 9B | Qwen3.5 4B |
|---|---:|---:|
| Phase 1 | 11 / 11 | 3 / 11 |
| Phase 2 | 7 / 7 | 5 / 7 |
| Phase 3 | 22 / 23 (95.7%) | 17 / 23 (73.9%) |
| Phase 2 average mission latency | 8863.1 ms | 11101.2 ms |
| Phase 2 average steps | 3.6 | 5.4 |

The smaller model reduced latency for many individual calls, but that did not translate into faster task completion. Because it made more mistakes, it required more actions and produced a higher average full-mission latency.

This is an important system-level result:

> Lower model inference latency does not necessarily mean lower robot task latency.

### Decision

Qwen3.5 4B will not be used as the current Milestone 1 baseline.

The reason is not simply that it scored lower. Its failures are in areas that matter directly to safe and useful robot behavior:

- left/right spatial reasoning
- choosing movement distances
- knowing when more sensing is required
- maintaining a correct plan across multiple steps

The 9B model is slower per inference but is significantly more reliable, needs fewer actions to finish a mission, and has been repeatable across multiple benchmark runs.

For now, Qwen3.5 9B remains the baseline. The project will not spend more time tuning the 4B model because the current goal is to validate the overall robot architecture, not optimize a weaker model prematurely.

Optimization can be revisited later if latency becomes a blocking system requirement. Possible future approaches include a different small model, quantization/runtime tuning, reducing model-call frequency, or moving fast continuous control into deterministic C++ while using the model only for higher-level decisions.
