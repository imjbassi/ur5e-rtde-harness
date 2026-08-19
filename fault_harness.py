#!/usr/bin/env python3
"""
fault_harness.py — deliberately induce RTDE failures and characterize how the
client actually behaves under each.

The question this answers:

    Which RTDE failures raise a catchable Python exception, and which ones
    kill the process outright?

That distinction determines how you defend against them. A catchable exception
can be handled with try/except and a reconnect. A segfault in the C++ layer
beneath the bindings cannot — the only defense is supervising the process from
outside and restarting it.

Every fault prints a structured result block. Copy those into
docs/fault-catalog.md as you go.

IMPORTANT: run each fault in a SEPARATE process invocation. A fault that
crashes the interpreter will take the whole script with it — which is itself
the result you're recording.

Usage:
    python fault_harness.py --list
    python fault_harness.py --fault dead_host
    python fault_harness.py --fault connection_drop
"""

import argparse
import math
import os
import subprocess
import sys
import time

try:
    from rtde_control import RTDEControlInterface
    from rtde_receive import RTDEReceiveInterface
except ImportError:
    print("[FAIL] ur_rtde not installed. Run: pip install ur_rtde")
    sys.exit(1)

from telemetry_logger import TelemetryLogger, find_gaps


HOME = [0.0, -math.pi / 2, 0.0, -math.pi / 2, 0.0, 0.0]
FAR = [math.pi / 2, -math.pi / 3, math.pi / 3, -math.pi / 2, 0.0, 0.0]


def banner(name, description):
    print("=" * 68)
    print(f"FAULT: {name}")
    print(description)
    print("=" * 68)


def result(outcome, detail=""):
    print("\n" + "-" * 68)
    print(f"RESULT: {outcome}")
    if detail:
        print(detail)
    print("-" * 68)
    print("\nRecord this in docs/fault-catalog.md before running the next fault.")


# ----------------------------------------------------------------------
# Fault 1 — connect to a host with nothing listening
# ----------------------------------------------------------------------
def fault_dead_host(args):
    banner(
        "dead_host",
        "Connect to an IP where nothing is listening on the RTDE port.\n"
        "Tests: does it time out cleanly, hang forever, or crash?"
    )

    dead_ip = "192.0.2.1"   # TEST-NET-1, reserved and guaranteed unroutable
    print(f"Attempting connection to {dead_ip} (guaranteed dead)...")
    print("Timing the attempt — a clean failure should NOT hang indefinitely.\n")

    start = time.time()
    try:
        rtde_r = RTDEReceiveInterface(dead_ip)
        elapsed = time.time() - start
        result("UNEXPECTED SUCCESS",
               f"Connected in {elapsed:.1f}s to an address that should be dead.")
    except Exception as e:
        elapsed = time.time() - start
        result(
            "CAUGHT EXCEPTION",
            f"Failed after {elapsed:.1f}s\n"
            f"  Type: {type(e).__name__}\n"
            f"  Message: {e}\n\n"
            f"  Catchable in Python -> an application can handle this with\n"
            f"  try/except and retry logic."
        )


# ----------------------------------------------------------------------
# Fault 2 — command issued on a stale handle after disconnect
# ----------------------------------------------------------------------
def fault_stale_handle(args):
    banner(
        "stale_handle",
        "Connect, disconnect, then issue a motion command on the dead handle.\n"
        "This is the 'Bad file descriptor' path from the production traceback."
    )

    print(f"Connecting to {args.host}...")
    rtde_c = RTDEControlInterface(args.host)
    print("[OK] Connected")

    print("Disconnecting cleanly...")
    rtde_c.disconnect()
    print("[OK] Disconnected")

    print("\nNow issuing moveJ on the stale handle...")
    print("If this segfaults, the script dies here and prints nothing more.\n")
    sys.stdout.flush()   # flush before the risky call, so output survives a crash

    try:
        rtde_c.moveJ(HOME, 0.5, 0.3)
        result("NO ERROR",
               "The command silently did nothing on a disconnected handle.\n"
               "  Arguably worse than an exception — a caller has no signal\n"
               "  that the command never reached the robot.")
    except Exception as e:
        result(
            "CAUGHT EXCEPTION",
            f"  Type: {type(e).__name__}\n"
            f"  Message: {e}\n\n"
            f"  Catchable -> defensible with try/except."
        )


# ----------------------------------------------------------------------
# Fault 3 — connection dropped mid-motion (the real production scenario)
# ----------------------------------------------------------------------
def fault_connection_drop(args):
    banner(
        "connection_drop",
        "Start a long motion, then kill the URSim container mid-flight.\n"
        "This is the closest reproduction of the real production segfault."
    )

    if not args.container:
        print("This fault needs the URSim container name/id so it can be killed.")
        print("Find it with:  docker ps")
        print("Then re-run:   python fault_harness.py --fault connection_drop "
              "--container <name>")
        sys.exit(1)

    os.makedirs("logs", exist_ok=True)
    logpath = f"logs/fault_connection_drop_{int(time.time())}.csv"

    print(f"Connecting to {args.host}...")
    rtde_r = RTDEReceiveInterface(args.host)
    rtde_c = RTDEControlInterface(args.host)
    print("[OK] Connected")

    logger = TelemetryLogger(rtde_r, logpath, sample_hz=50)
    logger.start()

    print("\nMoving home first...")
    rtde_c.moveJ(HOME, 0.5, 0.3)

    print(f"\nStarting SLOW long move (gives time to kill the container)")
    print(f"Killing container '{args.container}' in 3 seconds...")
    sys.stdout.flush()

    # Kill the container from a background thread while the move is in flight
    import threading

    def kill_later():
        time.sleep(3)
        print(f"\n  >>> killing container {args.container}")
        sys.stdout.flush()
        subprocess.run(["docker", "kill", args.container],
                       capture_output=True)

    threading.Thread(target=kill_later, daemon=True).start()

    print("\nIssuing slow moveJ — connection will drop partway through.")
    print("If this segfaults, nothing after this line prints.\n")
    sys.stdout.flush()

    try:
        rtde_c.moveJ(FAR, 0.1, 0.05)   # deliberately slow
        result("COMPLETED",
               "The move finished despite the container being killed.\n"
               "  Check the telemetry log for gaps — the failure may have\n"
               "  been silent rather than absent.")
    except Exception as e:
        result(
            "CAUGHT EXCEPTION",
            f"  Type: {type(e).__name__}\n"
            f"  Message: {e}\n\n"
            f"  Catchable -> the client handled the drop gracefully."
        )
    finally:
        logger.stop()

    # Telemetry gaps are the evidence that survives even a hard crash
    print(f"\nTelemetry: {logpath}")
    gaps = find_gaps(logpath, expected_hz=50)
    if gaps:
        print(f"[!] {len(gaps)} gap(s) — the moment the connection died:")
        for start, end, duration in gaps:
            print(f"    {duration:.3f}s gap at t={start:.3f}")
    else:
        print("[?] No gaps — logger kept reading, which is worth investigating.")


# ----------------------------------------------------------------------
# Fault 4 — control interface on a powered-off robot
# ----------------------------------------------------------------------
def fault_no_control_script(args):
    banner(
        "no_control_script",
        "Connect RTDEControlInterface while the robot is POWERED OFF.\n"
        "Reproduces: 'Failed to start control script, before timeout of 5s'\n\n"
        "SETUP REQUIRED: on the teach pendant, power the robot OFF first."
    )

    input("Power the robot OFF on the pendant, then press Enter to continue...")

    print(f"\nAttempting control interface connection to {args.host}...")
    start = time.time()

    try:
        rtde_c = RTDEControlInterface(args.host)
        elapsed = time.time() - start
        result("UNEXPECTED SUCCESS",
               f"Control interface connected in {elapsed:.1f}s despite the\n"
               f"  robot being powered off. Verify the pendant state.")
        rtde_c.disconnect()
    except Exception as e:
        elapsed = time.time() - start
        result(
            "CAUGHT EXCEPTION",
            f"Failed after {elapsed:.1f}s\n"
            f"  Type: {type(e).__name__}\n"
            f"  Message: {e}\n\n"
            f"  Compare this message against the real production traceback."
        )


# ----------------------------------------------------------------------
# Fault 5 — receive interface with an invalid field name
# ----------------------------------------------------------------------
def fault_bad_field(args):
    banner(
        "bad_field",
        "Request a data field that doesn't exist in the RTDE output recipe.\n"
        "Tests whether schema errors fail at config time or at runtime.\n\n"
        "Directly analogous to the PI ValueError: 'Cannot declare pub field\n"
        "action/gello/joints/position which is not an action field of the robot'"
    )

    print(f"Connecting to {args.host} with an invalid variable name...\n")

    try:
        rtde_r = RTDEReceiveInterface(args.host, variables=["not_a_real_field"])
        result("NO ERROR AT CONNECT",
               "The bad field was accepted at connection time.\n"
               "  Schema validation is deferred — the failure will surface\n"
               "  later, at read time, further from its cause.")
    except Exception as e:
        result(
            "CAUGHT EXCEPTION AT CONNECT",
            f"  Type: {type(e).__name__}\n"
            f"  Message: {e}\n\n"
            f"  Fails fast at configuration time, before any motion —\n"
            f"  the better design. Same behavior as the PI ValueError,\n"
            f"  which caught a GELLO field on a UR5e before the run started."
        )


FAULTS = {
    "dead_host": (fault_dead_host,
                  "Connect to an IP with nothing listening"),
    "stale_handle": (fault_stale_handle,
                     "Issue a command after disconnect"),
    "connection_drop": (fault_connection_drop,
                        "Kill URSim mid-motion (needs --container)"),
    "no_control_script": (fault_no_control_script,
                          "Connect control interface to a powered-off robot"),
    "bad_field": (fault_bad_field,
                  "Request a nonexistent RTDE data field"),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--fault", help="Which fault to run")
    parser.add_argument("--container",
                        help="URSim container name (for connection_drop)")
    parser.add_argument("--list", action="store_true",
                        help="List available faults")
    args = parser.parse_args()

    if args.list or not args.fault:
        print("Available faults:\n")
        for name, (_, desc) in FAULTS.items():
            print(f"  {name:<20} {desc}")
        print("\nRun each in a separate invocation:")
        print("  python fault_harness.py --fault <name>")
        return

    if args.fault not in FAULTS:
        print(f"Unknown fault: {args.fault}")
        print(f"Available: {', '.join(FAULTS.keys())}")
        sys.exit(1)

    fn, _ = FAULTS[args.fault]
    fn(args)


if __name__ == "__main__":
    main()
