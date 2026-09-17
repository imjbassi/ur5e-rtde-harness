#!/usr/bin/env python3
"""
telemetry_logger.py — samples RTDE receive at a fixed rate into a CSV.

Runs in a background thread so motion commands aren't blocked by logging.

Why a fixed sample rate matters: this mirrors how real robot data pipelines
capture episodes. Every row is a synchronized snapshot of the arm's state at a
known timestamp, which is what makes the log usable for after-the-fact analysis
rather than just a stream of prints.

The gap-detection at the end is the diagnostically useful part. If the
connection drops mid-episode, the log doesn't contain an error — it contains a
*hole*. Detecting that hole is how you spot a fault that left no exception
behind, which is the same reasoning as heartbeat-gap detection on a CAN bus.
"""

import csv
import threading
import time


class TelemetryLogger:
    """Background CSV logger for RTDE receive telemetry."""

    def __init__(self, rtde_receive, filepath, sample_hz=50):
        if sample_hz <= 0:
            raise ValueError(f"sample_hz must be positive, got {sample_hz}")
        self.rtde_r = rtde_receive
        self.filepath = filepath
        self.interval = 1.0 / sample_hz
        self.sample_hz = sample_hz
        self._running = False
        self._thread = None
        self.sample_count = 0
        self.error_count = 0

    def _sample_loop(self):
        with open(self.filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp",
                "q0", "q1", "q2", "q3", "q4", "q5",           # joint positions
                "qd0", "qd1", "qd2", "qd3", "qd4", "qd5",     # joint velocities
                "tcp_x", "tcp_y", "tcp_z",                     # TCP position
                "robot_mode",
                "safety_mode",
            ])

            self._ready.set()   # header is on disk; find_gaps can read the file

            # Schedule on a monotonic clock so wall-clock adjustments (NTP,
            # DST) can't stall or burst the sampler. Row timestamps stay
            # wall-clock so they line up with other logs.
            next_sample = time.monotonic()
            while self._running:
                try:
                    ts = time.time()
                    q = self.rtde_r.getActualQ()
                    qd = self.rtde_r.getActualQd()
                    tcp = self.rtde_r.getActualTCPPose()
                    mode = self.rtde_r.getRobotMode()
                    safety = self.rtde_r.getSafetyMode()

                    writer.writerow(
                        [f"{ts:.6f}"]
                        + [f"{v:.6f}" for v in q]
                        + [f"{v:.6f}" for v in qd]
                        + [f"{v:.6f}" for v in tcp[:3]]
                        + [mode, safety]
                    )
                    f.flush()   # flush every row — a crash shouldn't lose the log
                    self.sample_count += 1

                except Exception as e:
                    # Don't die on a read error. If the connection dropped, the
                    # useful evidence is the GAP this leaves in the log, not a
                    # stack trace from the logger thread.
                    self.error_count += 1
                    if self.error_count <= 3:
                        print(f"  [logger] read error: {e}")

                next_sample += self.interval
                sleep_for = next_sample - time.monotonic()
                if sleep_for > 0:
                    time.sleep(sleep_for)
                else:
                    # Fell behind schedule — resync rather than accumulating drift
                    next_sample = time.monotonic()

    def _run(self):
        try:
            self._sample_loop()
        except Exception as e:
            # e.g. the log file couldn't be opened — surface it instead of
            # letting the thread die silently.
            print(f"  [logger] FATAL: {type(e).__name__}: {e}")
        finally:
            self._ready.set()

    def start(self):
        self._running = True
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        # Wait for the header to be written so a very short run still
        # produces a valid CSV for find_gaps().
        self._ready.wait(timeout=2.0)
        print(f"[logger] recording to {self.filepath} at {self.sample_hz} Hz")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                print("[logger] warning: sampler thread still blocked on a read")
        print(f"[logger] stopped — {self.sample_count} samples, "
              f"{self.error_count} read errors")


def find_gaps(filepath, threshold_multiplier=3.0, expected_hz=50):
    """
    Find gaps in a telemetry log where sampling stopped unexpectedly.

    A gap means the logger couldn't read for a stretch of time — the signature
    of a connection loss that may have left no exception anywhere else.

    Returns a list of (gap_start, gap_end, duration_seconds).
    """
    expected_interval = 1.0 / expected_hz
    threshold = expected_interval * threshold_multiplier

    timestamps = []
    try:
        with open(filepath, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    timestamps.append(float(row["timestamp"]))
                except (KeyError, TypeError, ValueError):
                    # Truncated last row from a hard crash mid-write
                    continue
    except FileNotFoundError:
        return []

    gaps = []
    for i in range(1, len(timestamps)):
        delta = timestamps[i] - timestamps[i - 1]
        if delta > threshold:
            gaps.append((timestamps[i - 1], timestamps[i], delta))

    return gaps


if __name__ == "__main__":
    # Standalone: analyze an existing log for gaps
    import sys

    if len(sys.argv) < 2:
        print("Usage: python telemetry_logger.py <logfile.csv> [expected_hz]")
        sys.exit(1)

    hz = float(sys.argv[2]) if len(sys.argv) > 2 else 50
    gaps = find_gaps(sys.argv[1], expected_hz=hz)
    if not gaps:
        print("No gaps detected — telemetry was continuous.")
    else:
        print(f"Found {len(gaps)} gap(s):")
        for start, end, duration in gaps:
            print(f"  {duration:.3f}s gap starting at t={start:.3f}")
