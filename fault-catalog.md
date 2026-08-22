# Fault Catalog

Every fault: method, what it's testing, and observed behavior.

**The question this catalog answers:** which RTDE failures raise a catchable
Python exception, and which ones kill the process outright? That distinction
determines whether an application can defend against a failure or whether the
only defense is external process supervision.

> Sections marked `[RECORD]` are filled in as you run each fault. Don't
> pre-fill them — a fault that behaves differently than expected is the most
> valuable result in the whole project, and only shows up if you record what
> actually happened.

---

## Baseline (healthy)

Run `motion_demo.py` first with the robot powered on and everything working.

```
[RECORD: paste the console output from a clean motion_demo.py run]
```

```
[RECORD: paste the "No telemetry gaps" confirmation, and note the log filename]
```

Every fault below gets compared against this: continuous telemetry, no gaps,
motion completes, no exceptions.

---

## Fault 1 — Dead host

**Method:** `python fault_harness.py --fault dead_host`

Connects to `192.0.2.1` (TEST-NET-1, reserved and guaranteed unroutable).

**Testing:** does a connection to a nonexistent host fail cleanly and promptly,
or hang indefinitely?

**Why it matters:** if a robot is powered down or a network path is broken, an
application that hangs forever on connect is much harder to operate than one
that fails in a few seconds with a clear error. This is the difference between
"the fleet dashboard shows the robot as unreachable" and "the fleet dashboard
just stops updating."

**Observed:**

```
[RECORD: the RESULT block from the harness — exception type, message, elapsed time]
```

**Catchable in Python?** `[RECORD: yes / no]`
**Time to fail:** `[RECORD: seconds]`

---

## Fault 2 — Stale handle

**Method:** `python fault_harness.py --fault stale_handle`

Connects, disconnects cleanly, then issues `moveJ` on the now-dead handle.

**Testing:** the "Bad file descriptor" path from the real production traceback —
what happens when code holds a connection object whose underlying socket is
already gone?

**Why it matters:** this is a very common real-world shape. A reconnect routine
that doesn't fully replace its handle, an object cached across a connection
loss, a retry loop reusing a stale reference. Whether that produces an
exception, a silent no-op, or a crash determines how badly it fails in
production.

**Observed:**

```
[RECORD: the RESULT block — or note that the script died with no output,
which is itself the result]
```

**Catchable in Python?** `[RECORD: yes / no / silent no-op]`

> **If the script printed nothing after "Now issuing moveJ on the stale
> handle":** it crashed. Record the shell exit code — `echo $?` immediately
> after. An exit code of **139** is SIGSEGV, matching the production traceback.

---

## Fault 3 — Connection drop mid-motion

**Method:**
```bash
docker ps                       # find the URSim container name
python fault_harness.py --fault connection_drop --container <name>
```

Starts a slow `moveJ`, then kills the URSim container 3 seconds in, while the
command is still in flight.

**Testing:** the closest reproduction of the real production failure — a
connection that dies *during* an active control operation, not between
operations.

**Why it matters:** this is the actual scenario behind the segfault. A clean
disconnect between commands is easy to handle; losing the controller mid-command
is where the C++ layer has a live socket it expects to still be valid.

**Observed:**

```
[RECORD: the RESULT block, or note if the script died silently]
```

**Catchable in Python?** `[RECORD: yes / no]`
**Exit code if it crashed:** `[RECORD: run echo $? right after]`

**Telemetry gap:**
```
[RECORD: the gap output — this is the key evidence]
```

> **Why the telemetry gap matters most here:** if the process crashed, there's
> no exception and no traceback in your application logs. But the CSV was
> flushed every row, so it survives the crash — and the gap in it marks the
> exact moment the connection died. That's evidence recovered from a failure
> that left nothing else behind.
>
> Same reasoning as heartbeat-gap detection on a CAN bus: the absence of
> expected data, at a known timestamp, is itself the diagnostic.

---

## Fault 4 — Control script fails to start

**Method:** power the robot **OFF** on the teach pendant, then:
```bash
python fault_harness.py --fault no_control_script
```

**Testing:** reproduces `ur_rtde: Failed to start control script, before
timeout of 5 seconds` — the exact error string from the production traceback.

**Why it matters:** `RTDEControlInterface` doesn't just open a socket. It
uploads and starts a control script on the controller, which requires the robot
to be powered with brakes released. This failure is common in practice: a
startup race where the software connects before the arm has finished powering
on.

**Observed:**

```
[RECORD: the RESULT block]
```

**Catchable in Python?** `[RECORD: yes / no]`
**Does the message match the production traceback?** `[RECORD]`

> **The operationally interesting question:** is this distinguishable from a
> network failure (fault 1) by the error message alone? If both produce a
> generic connection error, then "robot is off" and "robot is unreachable"
> look identical from the logs — which matters for triage, because they have
> completely different fixes.

---

## Fault 5 — Invalid data field

**Method:** `python fault_harness.py --fault bad_field`

Requests a nonexistent variable name in the RTDE output recipe.

**Testing:** does a schema error fail fast at configuration time, or silently
at read time later?

**Why it matters:** this is directly analogous to a real PI error —
`ValueError: Cannot declare pub field 'action/gello/joints/position' which is
not an action field of the robot` — where a config written for a GELLO-based
robot was pointed at a UR5e. That error fired at configuration time, before any
motion, which is the good outcome: the mismatch was caught by schema validation
rather than surfacing as mysterious runtime behavior.

**Observed:**

```
[RECORD: the RESULT block]
```

**Fails at connect time or at read time?** `[RECORD]`

---

## Summary table

`[RECORD: fill from your actual results]`

| Fault | Catchable? | Time to fail | Evidence left behind | Defense |
|---|---|---|---|---|
| Dead host | | | | |
| Stale handle | | | | |
| Connection drop mid-motion | | | | |
| No control script | | | | |
| Invalid data field | | | | |

**Defense column** — how an application can actually protect against each:
- *try/except* — catchable, handle in application code
- *process supervision* — kills the interpreter, only recoverable by an
  external supervisor restarting the process
- *validation* — caught at config time, before anything runs

---

## What this catalog is for

`[RECORD: write this last, from what you actually found]`

Prompts worth answering:

- **Which failures were catchable, and which weren't?** The split matters more
  than any individual result. Anything not catchable can't be defended against
  in application code at all.
- **Did any fault fail silently** — no exception, no crash, but the command
  didn't reach the robot? That's the worst outcome, because it produces no
  signal anywhere.
- **Were any two faults indistinguishable from their error messages alone?**
  If "robot powered off" and "network unreachable" look the same in the logs,
  triage costs more than it should.
- **What did telemetry gaps catch that exceptions didn't?** This is the
  strongest argument for logging state continuously rather than relying only on
  error handling.
