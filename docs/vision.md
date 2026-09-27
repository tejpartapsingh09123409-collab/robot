# Project Vision

## Goal

Build a general-purpose embodied robot that can understand high-level human commands, perceive its environment, reason about what needs to happen, and compose available physical capabilities to accomplish the requested task.

The project is an experiment toward increasingly human-like general capability. Rather than training a foundation model ourselves, we will integrate the most capable models our available hardware can reasonably support and progressively expand the robot's perception, memory, reasoning, and physical abilities.

## Example

A human should eventually be able to give a high-level command such as:

> Go put this on the desk.

The robot should determine the required steps itself, for example:

1. Understand the requested goal.
2. Observe and interpret the environment.
3. Locate the referenced object.
4. Approach and grasp it.
5. Locate the desk.
6. Navigate to the desk.
7. Place the object.
8. Observe the result and determine whether the task succeeded.

The system should not depend on a dedicated `put_this_on_desk()` behavior. Instead, increasingly general capabilities for perception, movement, manipulation, sensing, reasoning, and memory should be composable by the intelligence layer to accomplish new tasks.

## Technology Principle

The project is not tied permanently to LLMs or any single AI architecture.

We will use the best practical intelligence technology available to us, subject to our hardware, safety, and engineering constraints. As the field evolves, that may include multimodal foundation models, vision-language-action models, world models, or other approaches.

## Engineering Principle

High-level intelligence decides what should be done. Deterministic lower-level systems remain responsible for real-time control and safety-critical behavior.

The project will grow capability incrementally: build a small working system, observe its limitations, and add the next primitive or subsystem required to make it more general.
