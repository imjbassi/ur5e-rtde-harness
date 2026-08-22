# RTDE Notes

Background on the protocol, why the failure modes look the way they do, and how
this connects to the wider robotics stack.

---

## What RTDE is

**RTDE (Real-Time Data Exchange)** is Universal Robots' protocol for exchanging
data with a UR controller over Ethernet, on TCP port **30004**.

It's not a request/response API. It's a **synchronized streaming interface**:
the client registers which fields it wants ("output recipe") and which it will
send ("input recipe"), and then the controller pushes data at a fixed rate — up
to **500 Hz** on the e-Series — while the client pushes commands back on the
same connection.

The recipe negotiation at setup is why fault 5 (invalid field name) is
interesting: if the protocol validates recipes at registration time, a bad field
fails immediately, before any motion. If it doesn't, the same mistake surfaces
much later and much further from its cause.

---

## The three interfaces

| Interface | Port | What it does |
|---|---|---|
| `RTDEControlInterface` | 30004 | Sends motion commands: `moveJ`, `moveL`, `servoJ`, `speedJ`, `stopJ` |
| `RTDEReceiveInterface` | 30004 | Reads joint positions/velocities/currents, TCP pose, robot mode, safety state |
| `DashboardClient` | 29999 | Power on/off, brake release, load and run programs, query robot state |

**The important asymmetry:** `RTDEReceiveInterface` only reads, so it works
even on a powered-off robot — you'll get valid data and no motion.
`RTDEControlInterface` **uploads and starts a control script** on the
controller, which requires power and released brakes.

That's why `connect_test.py` checks them in that order. Receive working while
Control fails tells you precisely where the problem is: the network path is
fine, the robot just isn't ready to move.

---

## Why segfaults are possible at all

`ur_rtde` is a **C++ library with Python bindings**. Your Python code calls into
compiled C++ that owns the actual sockets and buffers.

Python's exception machinery only protects Python-level code. When something
goes wrong *inside* the C++ layer — dereferencing an invalidated socket handle,
reading a buffer that was freed when a connection dropped — there's no Python
exception to raise. The process receives **SIGSEGV** and dies immediately.

This is exactly what the production traceback showed:

```
RTDEControlInterface: Could not receive data from robot...
RTDEControlInterface: Exception: available: Bad file descriptor
Reconnecting...
RTDEControlInterface: Robot is disconnected, reconnecting...
ur_rtde: Failed to start control script, before timeout of 5 seconds
Fatal Python error: Segmentation fault
```

Note the sequence: the library **noticed** the disconnect ("Bad file
descriptor"), **tried to reconnect**, **failed to restart the control script**,
and *then* crashed. The error handling partially worked and then hit a case it
couldn't handle.

Container **exit code 139** confirmed the cause: `128 + 11`, where signal 11 is
SIGSEGV. Any exit code above 128 encodes a fatal signal this way, and it's worth
recognizing on sight — `139` means segfault, `137` means SIGKILL (often an
out-of-memory kill).

**Why this matters operationally:** a segfault cannot be caught by `try/except`.
No amount of application-level error handling defends against it. The only
mitigations are external — a supervisor process that restarts on crash, or a
patched/updated library version.

---

## Joint-space vs. Cartesian commands

| Command | Takes | Requires IK? |
|---|---|---|
| `moveJ` | Six joint angles (radians) | No |
| `moveL` | A TCP pose (x, y, z, rx, ry, rz) | Yes |

`motion_demo.py` uses `moveJ` deliberately. Cartesian commands need inverse
kinematics, which introduces its own failure modes — unreachable targets,
singularities, ambiguous multi-solution configurations. Testing connection
faults with IK in the path muddies the results: an unreachable-pose failure and
a connection failure would both show up as "the move didn't happen."

Same reasoning behind GELLO-style teleop mapping joint-to-joint instead of
going through Cartesian space — fewer moving parts in the path you're not
trying to test.

---

## Robot modes

`getRobotMode()` returns an integer. The two worth knowing on sight:

| Code | Mode | Meaning |
|---|---|---|
| 3 | POWER_OFF | Arm unpowered |
| 4 | POWER_ON | Powered, brakes still engaged |
| **5** | **IDLE** | Powered, brakes engaged, **not ready for motion** |
| 6 | BACKDRIVE | Manual freedrive |
| **7** | **RUNNING** | Brakes released, **ready for motion** |

**5 vs. 7 is the distinction that matters.** A robot in mode 5 looks powered on
and will happily accept a receive connection, but `RTDEControlInterface` will
fail because the brakes are still engaged. That's fault 4, and it's a common
real startup race: software connects before the arm has finished releasing
brakes.

---

## Why URSim is a legitimate test target

URSim runs the **actual PolyScope controller software** in a container, not a
reimplementation. Same RTDE stack, same control script upload path, same
protocol version negotiation.

What it does **not** simulate: real physics, real motor dynamics, real safety
hardware, real network conditions.

So this harness is a valid test of **protocol and connection-layer behavior** —
what happens when a connection drops, when a handle goes stale, when a control
script won't start. It is **not** a test of physical failure modes: joint
overcurrent, encoder faults, brake failures, collisions. Those need real
hardware.

Worth stating plainly in any writeup. The claim is "I characterized RTDE
connection-failure behavior against the official simulator," not "I tested a
UR5e."

---

## Where this sits relative to other layers

| Layer | Protocol | Failure modes | Project |
|---|---|---|---|
| Physical bus | CAN | Termination, connectors, bus-off | `can-bus-fault-injector` |
| Device driver | USB / `gs_usb` | Enumeration, wrong mode, wedged firmware | (same) |
| Network control | RTDE / TCP | Connection drop, stale handle, control script failure | **this project** |
| Policy serving | HTTP / gRPC to a GPU server | Cold start, inference timeout, session disconnect | (observed at work) |

The common structure across all four: **something is "connected" while not
being functional**, and the diagnostic question is always the same — is it there
*as the thing you expect*, and is it *answering*?
