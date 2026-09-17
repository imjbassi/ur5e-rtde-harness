#!/usr/bin/env python3
"""
motion_demo.py — drive the UR5e through a joint-space motion sequence while
logging synchronized telemetry.

This is the "healthy baseline" for the fault harness. Run it first and keep the
resulting CSV — every fault run gets compared against it, the same way every
CAN bus fault was compared against a clean ERROR-ACTIVE baseline.

Uses moveJ (joint-space) rather than moveL (linear/Cartesian) deliberately.
moveJ takes joint angles directly, so no inverse kinematics is involved and
there's no chance of an unreachable-pose or singularity failure muddying the
results. Same reasoning as GELLO-style teleop avoiding IK entirely: fewer
failure modes in the path you're not trying to test.

Usage:
    python motion_demo.py
    python motion_demo.py --host 192.168.1.50 --cycles 3
"""

import argparse
import math
import os
import sys
import time

try:
    from rtde_control import RTDEControlInterface
    from rtde_receive import RTDEReceiveInterface
except ImportError:
    print("[FAIL] ur_rtde not installed. Run: pip install ur_rtde")
    sys.exit(1)

from telemetry_logger import TelemetryLogger, find_gaps


# Joint angles in radians: [base, shoulder, elbow, wrist1, wrist2, wrist3]
# Conservative amplitudes — well inside joint limits, no self-collision risk.
HOME = [0.0, -math.pi / 2, 0.0, -math.pi / 2, 0.0, 0.0]

WAYPOINTS = [
    [0.0,            -math.pi / 2,  0.0,          -math.pi / 2, 0.0, 0.0],
    [math.pi / 6,    -math.pi / 2,  math.pi / 6,  -math.pi / 2, 0.0, 0.0],
    [math.pi / 6,    -math.pi / 3,  math.pi / 4,  -math.pi / 2, 0.0, 0.0],
    [-math.pi / 6,   -math.pi / 3,  math.pi / 4,  -math.pi / 2, 0.0, 0.0],
    [-math.pi / 6,   -math.pi / 2,  0.0,          -math.pi / 2, 0.0, 0.0],
]

VELOCITY = 0.5      # rad/s
ACCELERATION = 0.3  # rad/s^2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--cycles", type=int, default=2,
                        help="How many times to run the waypoint sequence")
    parser.add_argument("--log", default=None,
                        help="Output CSV path (default: logs/baseline_<ts>.csv)")
    parser.add_argument("--hz", type=int, default=50,
                        help="Telemetry sample rate")
    args = parser.parse_args()
    if args.hz <= 0:
        parser.error("--hz must be positive")
    if args.cycles < 0:
        parser.error("--cycles must be >= 0")

    if args.log is None:
        args.log = f"logs/baseline_{int(time.time())}.csv"
    log_dir = os.path.dirname(args.log)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    # --- Connect --------------------------------------------------------
    print(f"Connecting to {args.host}...")
    try:
        rtde_r = RTDEReceiveInterface(args.host)
        rtde_c = RTDEControlInterface(args.host)
    except Exception as e:
        print(f"[FAIL] Connection failed: {e}")
        print("       Run connect_test.py first to isolate the problem.")
        sys.exit(1)
    print("[OK] Connected\n")

    # --- Start logging --------------------------------------------------
    logger = TelemetryLogger(rtde_r, args.log, sample_hz=args.hz)
    logger.start()

    # --- Move -----------------------------------------------------------
    try:
        print("Moving to home position...")
        rtde_c.moveJ(HOME, VELOCITY, ACCELERATION)

        for cycle in range(args.cycles):
            print(f"\nCycle {cycle + 1}/{args.cycles}")
            for i, wp in enumerate(WAYPOINTS):
                print(f"  waypoint {i + 1}/{len(WAYPOINTS)}")
                rtde_c.moveJ(wp, VELOCITY, ACCELERATION)

        print("\nReturning home...")
        rtde_c.moveJ(HOME, VELOCITY, ACCELERATION)
        print("[OK] Motion sequence complete")

    except KeyboardInterrupt:
        print("\n[!] Interrupted — stopping robot")
        try:
            rtde_c.stopJ(2.0)
        except Exception:
            pass

    except Exception as e:
        # A caught exception here is itself a result worth recording:
        # it means the failure was recoverable at the Python layer.
        print(f"\n[FAIL] Motion failed with a catchable exception:")
        print(f"       {type(e).__name__}: {e}")

    finally:
        logger.stop()
        # Disconnect each independently — a failure on one shouldn't leak the other
        for iface in (rtde_c, rtde_r):
            try:
                iface.disconnect()
            except Exception:
                pass

    # --- Analyze --------------------------------------------------------
    print(f"\nTelemetry written to {args.log}")
    gaps = find_gaps(args.log, expected_hz=args.hz)
    if gaps:
        print(f"[!] {len(gaps)} telemetry gap(s) detected:")
        for start, end, duration in gaps:
            print(f"    {duration:.3f}s gap at t={start:.3f}")
        print("    Gaps in a clean baseline run usually mean the sample rate")
        print("    is too high for this machine — try --hz 20.")
    else:
        print("[OK] No telemetry gaps — continuous capture")


if __name__ == "__main__":
    main()
