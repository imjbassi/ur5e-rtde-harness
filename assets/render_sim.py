#!/usr/bin/env python3
"""
render_sim.py — render a short clip of the UR5e waypoint cycle from
motion_demo.py as a kinematically accurate 3D animation.

Uses the UR5e's published DH parameters for forward kinematics and replays
the exact HOME/WAYPOINTS sequence that motion_demo.py sends over RTDE, with
smooth joint-space interpolation approximating moveJ at 0.5 rad/s.

Output: assets/ur5e_sim.gif

Usage:
    pip install matplotlib numpy pillow
    python assets/render_sim.py
"""

import math

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation, PillowWriter

# ---------------------------------------------------------------------------
# UR5e kinematics — standard DH parameters (Universal Robots datasheet)
# ---------------------------------------------------------------------------
DH_A = [0.0, -0.425, -0.3922, 0.0, 0.0, 0.0]
DH_D = [0.1625, 0.0, 0.0, 0.1333, 0.0997, 0.0996]
DH_ALPHA = [math.pi / 2, 0.0, 0.0, math.pi / 2, -math.pi / 2, 0.0]


def dh_transform(theta, d, a, alpha):
    ct, st = math.cos(theta), math.sin(theta)
    ca, sa = math.cos(alpha), math.sin(alpha)
    return np.array([
        [ct, -st * ca,  st * sa, a * ct],
        [st,  ct * ca, -ct * sa, a * st],
        [0.0,      sa,       ca,      d],
        [0.0,     0.0,      0.0,    1.0],
    ])


def joint_positions(q):
    """Return the xyz of the base and each joint frame origin, shape (7, 3)."""
    T = np.eye(4)
    pts = [T[:3, 3].copy()]
    for i in range(6):
        T = T @ dh_transform(q[i], DH_D[i], DH_A[i], DH_ALPHA[i])
        pts.append(T[:3, 3].copy())
    return np.array(pts)


# ---------------------------------------------------------------------------
# Trajectory — same sequence motion_demo.py sends over RTDE (one cycle)
# ---------------------------------------------------------------------------
HOME = [0.0, -math.pi / 2, 0.0, -math.pi / 2, 0.0, 0.0]

WAYPOINTS = [
    [0.0,          -math.pi / 2, 0.0,         -math.pi / 2, 0.0, 0.0],
    [math.pi / 6,  -math.pi / 2, math.pi / 6, -math.pi / 2, 0.0, 0.0],
    [math.pi / 6,  -math.pi / 3, math.pi / 4, -math.pi / 2, 0.0, 0.0],
    [-math.pi / 6, -math.pi / 3, math.pi / 4, -math.pi / 2, 0.0, 0.0],
    [-math.pi / 6, -math.pi / 2, 0.0,         -math.pi / 2, 0.0, 0.0],
]

VELOCITY = 0.5  # rad/s, matches motion_demo.py

FPS = 20


def minimum_jerk(s):
    """Smooth 0->1 time scaling with zero boundary velocity/acceleration."""
    return 10 * s**3 - 15 * s**4 + 6 * s**5


def build_trajectory():
    """Interpolate HOME -> waypoints -> HOME the way moveJ paces segments."""
    sequence = [HOME] + WAYPOINTS + [HOME]
    qs, ts = [], []
    t = 0.0
    for a, b in zip(sequence[:-1], sequence[1:]):
        a, b = np.array(a), np.array(b)
        dq = np.max(np.abs(b - a))
        duration = max(dq / VELOCITY * 1.4, 0.4)  # 1.4x for accel/decel ramps
        n = max(int(duration * FPS), 2)
        for k in range(n):
            s = minimum_jerk(k / n)
            qs.append(a + s * (b - a))
            ts.append(t + duration * k / n)
        t += duration
    qs.append(np.array(HOME))
    ts.append(t)
    return np.array(qs), np.array(ts)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
LINK_COLOR = "#3b5b7d"
JOINT_COLOR = "#1a2e40"
TRACE_COLOR = "#c05a4e"
JOINT_TRACE_COLORS = ["#3b5b7d", "#c05a4e", "#5b8a72", "#8a6d9c", "#b08a3e", "#7a7a7a"]


def main():
    Q, T = build_trajectory()
    tcp = np.array([joint_positions(q)[-1] for q in Q])

    fig = plt.figure(figsize=(9.0, 4.3), dpi=96, facecolor="white")
    ax3d = fig.add_axes([0.0, 0.02, 0.52, 0.90], projection="3d")
    axq = fig.add_axes([0.62, 0.14, 0.35, 0.68])

    fig.suptitle(
        "UR5e joint-space waypoint cycle  (motion_demo.py, moveJ @ 0.5 rad/s)",
        fontsize=10.5, y=0.97, color="#222222",
    )

    # --- 3D panel styling ------------------------------------------------
    ax3d.set_facecolor("white")
    for pane in (ax3d.xaxis.pane, ax3d.yaxis.pane, ax3d.zaxis.pane):
        pane.set_facecolor("white")
        pane.set_edgecolor("#dddddd")
    ax3d.grid(True)
    ax3d.xaxis._axinfo["grid"].update(color="#e8e8e8", linewidth=0.5)
    ax3d.yaxis._axinfo["grid"].update(color="#e8e8e8", linewidth=0.5)
    ax3d.zaxis._axinfo["grid"].update(color="#e8e8e8", linewidth=0.5)
    ax3d.set_xlim(-0.7, 0.7)
    ax3d.set_ylim(-0.7, 0.7)
    ax3d.set_zlim(0.0, 0.9)
    ax3d.set_box_aspect((1, 1, 0.64))
    ax3d.set_xlabel("x [m]", fontsize=7, labelpad=-4, color="#555555")
    ax3d.set_ylabel("y [m]", fontsize=7, labelpad=-4, color="#555555")
    ax3d.set_zlabel("z [m]", fontsize=7, labelpad=-4, color="#555555")
    ax3d.tick_params(labelsize=6, colors="#888888", pad=-2)
    ax3d.view_init(elev=22, azim=-55)

    # Base pedestal
    theta = np.linspace(0, 2 * math.pi, 40)
    ax3d.plot(0.09 * np.cos(theta), 0.09 * np.sin(theta),
              np.zeros_like(theta), color="#bbbbbb", lw=1.0)

    (arm_line,) = ax3d.plot([], [], [], "-", color=LINK_COLOR, lw=4.5,
                            solid_capstyle="round", zorder=5)
    (joint_dots,) = ax3d.plot([], [], [], "o", color=JOINT_COLOR,
                              markersize=5, zorder=6)
    (tcp_dot,) = ax3d.plot([], [], [], "o", color=TRACE_COLOR,
                           markersize=6, zorder=7)
    (tcp_trace,) = ax3d.plot([], [], [], "-", color=TRACE_COLOR,
                             lw=1.0, alpha=0.6, zorder=4)

    time_label = ax3d.text2D(0.03, 0.02, "", transform=ax3d.transAxes,
                             fontsize=8, color="#555555", family="monospace")

    # --- Joint-trace panel styling ---------------------------------------
    axq.set_facecolor("white")
    for spine in ("top", "right"):
        axq.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        axq.spines[spine].set_color("#999999")
        axq.spines[spine].set_linewidth(0.8)
    axq.tick_params(labelsize=7, colors="#555555")
    axq.set_xlim(0, T[-1])
    axq.set_ylim(math.degrees(Q.min()) - 12, math.degrees(Q.max()) + 12)
    axq.set_xlabel("t [s]", fontsize=8, color="#555555")
    axq.set_ylabel("joint angle [deg]", fontsize=8, color="#555555")
    axq.set_title("target_q telemetry", fontsize=9, color="#333333")

    qlines = []
    names = [r"$q_1$", r"$q_2$", r"$q_3$", r"$q_4$", r"$q_5$", r"$q_6$"]
    for j in range(6):
        (ln,) = axq.plot([], [], "-", color=JOINT_TRACE_COLORS[j],
                         lw=1.2, label=names[j])
        qlines.append(ln)
    cursor = axq.axvline(0.0, color="#bbbbbb", lw=0.8)
    axq.legend(loc="upper right", fontsize=6.5, ncol=3, frameon=False,
               columnspacing=0.9, handlelength=1.2)

    Qdeg = np.degrees(Q)

    def update(i):
        pts = joint_positions(Q[i])
        arm_line.set_data(pts[:, 0], pts[:, 1])
        arm_line.set_3d_properties(pts[:, 2])
        joint_dots.set_data(pts[1:-1, 0], pts[1:-1, 1])
        joint_dots.set_3d_properties(pts[1:-1, 2])
        tcp_dot.set_data([pts[-1, 0]], [pts[-1, 1]])
        tcp_dot.set_3d_properties([pts[-1, 2]])
        tcp_trace.set_data(tcp[: i + 1, 0], tcp[: i + 1, 1])
        tcp_trace.set_3d_properties(tcp[: i + 1, 2])
        time_label.set_text(f"t = {T[i]:5.2f} s")
        for j, ln in enumerate(qlines):
            ln.set_data(T[: i + 1], Qdeg[: i + 1, j])
        cursor.set_xdata([T[i]])
        return []

    anim = FuncAnimation(fig, update, frames=len(Q), interval=1000 / FPS)
    out = "assets/ur5e_sim.gif"
    anim.save(out, writer=PillowWriter(fps=FPS))
    print(f"wrote {out}: {len(Q)} frames, {T[-1]:.1f} s at {FPS} fps")


if __name__ == "__main__":
    main()
