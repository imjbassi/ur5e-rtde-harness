# Setup

Getting URSim running and `ur_rtde` talking to it. Budget about 30 minutes the
first time.

---

## 1. Prerequisites

- **Docker** — https://docs.docker.com/get-docker/
- **Python 3.8+**
- A web browser (the virtual teach pendant runs in-browser via noVNC)

On Windows, Docker Desktop with the WSL2 backend. You already have WSL2 set up
from the CAN bus project, so this should be straightforward.

---

## 2. Start URSim

URSim is Universal Robots' official offline simulator. It runs the **actual
controller software** — the same PolyScope interface and the same RTDE
implementation as a physical UR5e, just without the hardware attached.

```bash
docker run --rm -it \
  -p 5900:5900 \
  -p 6080:6080 \
  -p 29999:29999 \
  -p 30001-30004:30001-30004 \
  universalrobots/ursim_e-series
```

**What each port does:**

| Port | Purpose |
|---|---|
| 6080 | noVNC — the teach pendant in your browser |
| 5900 | Raw VNC, if you'd rather use a VNC client |
| 29999 | Dashboard server — power on/off, load programs, query state |
| 30001–30003 | Primary/secondary/real-time client interfaces |
| **30004** | **RTDE — the one this project actually uses** |

First run pulls a few GB. Startup takes a minute or two after that.

**Note on the image name:** `ursim_e-series` covers the e-Series family, which
includes the UR5e. If UR renames or retags images, check Docker Hub under the
`universalrobots` org for the current tag.

---

## 3. Power on the virtual robot

Open **http://localhost:6080/vnc.html** and connect. You'll get the PolyScope
teach pendant interface — identical to the one on a real UR5e cell.

Then:

1. Tap the **red/status button** at the bottom-left
2. **Power On**
3. **Start** (releases the brakes)
4. Status should read **Normal** / green

**This step is not optional.** RTDE will connect to a powered-off robot but
`RTDEControlInterface` will fail to start its control script — which is
*exactly* fault 4 in the catalog, and a real failure mode worth seeing
deliberately once you've got everything else working.

---

## 4. Install the client library

```bash
pip install ur_rtde
```

If the wheel doesn't build on your platform, UR's docs cover building from
source: https://sdurobotics.gitlab.io/ur_rtde/

---

## 5. Verify

```bash
python connect_test.py
```

Expected:

```
[OK] Connected to RTDE receive interface at 127.0.0.1
[OK] Robot mode: 7 (RUNNING)
[OK] Joint positions (rad): [0.0, -1.5708, 0.0, -1.5708, 0.0, 0.0]
[OK] Control interface connected
```

If it hangs or refuses, see the networking section below.

---

## 6. WSL2 / Windows networking — read this before debugging anything else

This is the most common setup failure, and it's the same class of problem you
already hit with USB passthrough on the CAN bus project.

**If Docker Desktop runs with the WSL2 backend and your Python script runs
inside WSL2**, `127.0.0.1` may not resolve to the container the way you expect.
Options, in order of least fuss:

1. **Run the Python scripts from Windows directly** (not inside WSL2) —
   `localhost` port forwarding from Docker Desktop generally just works
2. **Find the container's actual IP** and use that instead of `127.0.0.1`:
   ```bash
   docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' <container_id>
   ```
   then pass `--host <that_ip>` to the scripts
3. **Use `host.docker.internal`** as the host, which Docker Desktop provides
   specifically for this

Every script in `src/` accepts `--host` so you can point at whichever address
actually works without editing code.

**Quick check that the port is reachable at all:**

```bash
# Linux/WSL2
nc -zv 127.0.0.1 30004

# Windows PowerShell
Test-NetConnection -ComputerName localhost -Port 30004
```

If that fails, it's networking, not `ur_rtde` — don't debug the Python until
this succeeds.

---

## 7. Troubleshooting

**"Failed to start control script"**
Robot isn't powered on / brakes not released. Go back to step 3. (Or you're
deliberately reproducing fault 4, in which case: working as intended.)

**Connection refused on 30004**
Container isn't running, ports weren't published, or the WSL2 issue above.
Check `docker ps` first.

**Script connects but joint values never change**
`RTDEReceiveInterface` works while the robot is powered off — you'll get valid
reads and no motion. Confirm the pendant shows **Normal**, not
**Power off** / **Idle**.

**Segfault instead of an exception**
That's not a bug in your setup. That's the thing this project exists to
document. See `fault-catalog.md`.
