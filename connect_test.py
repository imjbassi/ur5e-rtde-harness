#!/usr/bin/env python3
"""
connect_test.py — minimal RTDE connection verification.

Run this FIRST, before anything else. It separates "my networking/URSim setup
is broken" from "my control code is broken" — the same principle as running the
MCP2515 loopback test before wiring up a CAN bus.

Checks, in increasing order of what they prove:
  1. Receive interface connects            -> network path to port 30004 works
  2. Robot mode is readable                -> controller is responding
  3. Joint positions are readable          -> telemetry stream is live
  4. Control interface connects            -> control script started (needs
                                              the robot POWERED ON)

Step 4 is the one that fails if the robot is powered off or brakes are engaged.
That failure is real and expected in that state — it's fault 4 in the catalog.

Usage:
    python connect_test.py
    python connect_test.py --host 192.168.1.50
"""

import argparse
import sys

try:
    from rtde_receive import RTDEReceiveInterface
    from rtde_control import RTDEControlInterface
except ImportError:
    print("[FAIL] ur_rtde not installed. Run: pip install ur_rtde")
    sys.exit(1)


# Robot mode codes reported by the controller. Worth knowing 5 vs 7:
# 5 = powered but brakes engaged, 7 = fully running and ready for motion.
ROBOT_MODES = {
    -1: "NO_CONTROLLER",
    0: "DISCONNECTED",
    1: "CONFIRM_SAFETY",
    2: "BOOTING",
    3: "POWER_OFF",
    4: "POWER_ON",
    5: "IDLE",
    6: "BACKDRIVE",
    7: "RUNNING",
    8: "UPDATING_FIRMWARE",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1",
                        help="Robot/URSim IP (default: 127.0.0.1)")
    args = parser.parse_args()

    print(f"Testing RTDE connection to {args.host}\n")

    # --- 1. Receive interface -------------------------------------------
    try:
        rtde_r = RTDEReceiveInterface(args.host)
        print(f"[OK]   Connected to RTDE receive interface at {args.host}")
    except Exception as e:
        print(f"[FAIL] Could not connect receive interface: {e}")
        print("       Check: is URSim running? Is port 30004 reachable?")
        print("       See docs/setup.md, section 6 (WSL2 networking).")
        sys.exit(1)

    # --- 2. Robot mode --------------------------------------------------
    try:
        mode = rtde_r.getRobotMode()
        mode_name = ROBOT_MODES.get(mode, "UNKNOWN")
        print(f"[OK]   Robot mode: {mode} ({mode_name})")
        if mode != 7:
            print(f"       ! Mode is not RUNNING. Power on and release brakes")
            print(f"         on the teach pendant, or step 4 below will fail.")
    except Exception as e:
        print(f"[FAIL] Could not read robot mode: {e}")

    # --- 3. Joint telemetry ---------------------------------------------
    try:
        q = rtde_r.getActualQ()
        formatted = [f"{v:.4f}" for v in q]
        print(f"[OK]   Joint positions (rad): [{', '.join(formatted)}]")
    except Exception as e:
        print(f"[FAIL] Could not read joint positions: {e}")

    # --- 4. Control interface -------------------------------------------
    # This is the step that actually starts a control script on the
    # controller. It requires the robot to be powered on with brakes
    # released. This is also the call that segfaulted in the real
    # production traceback this project is built around.
    try:
        rtde_c = RTDEControlInterface(args.host)
        print(f"[OK]   Control interface connected — control script running")
        rtde_c.disconnect()
    except Exception as e:
        print(f"[FAIL] Control interface failed: {e}")
        print("       Most likely: robot is not powered on / brakes engaged.")
        print("       This is fault 4 in docs/fault-catalog.md.")
        sys.exit(1)

    print("\nAll checks passed. Ready to run motion_demo.py")


if __name__ == "__main__":
    main()
