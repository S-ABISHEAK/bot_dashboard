# FleetNet Dashboard — Context & Full UI Inventory (for UI redesign)

## 1. What this project is

**FleetNet** is a live, browser-based operations console for a **simulated decentralised fleet of Autonomous Mobile Robots (AMRs)** working a warehouse. It was built for a Smart India Hackathon (SIH)-style demo: the pitch is that a warehouse robot fleet can coordinate itself with **no central brain** — if the dashboard is killed, the robots keep working, because all the intelligence lives in five algorithm layers running independently per-robot:

1. **D\* Lite** — per-robot path planning around racks/dropped obstacles
2. **MD-PIBT** — conflict-free next-cell movement + priority inheritance (multi-agent pathfinding)
3. **NH-ORCA** — reciprocal local collision avoidance between nearby robots
4. **ACBBA** — decentralised auction-based task allocation (robots bid for jobs)
5. **Zenoh-style comms mesh** — pub/sub robot-to-robot networking, with simulated Wi-Fi dead zones

The Python backend (FastAPI + a physics/algorithm engine) is the **authoritative simulation** — it computes every robot's position, battery, task, and decision every tick (100ms) and streams it to the browser over a WebSocket. **The browser is a pure view + control surface** — it renders what the server sends and sends back button clicks as HTTP POSTs. No simulation logic runs in JavaScript.

### Why the dashboard exists
It's a **demo/observability tool**, used to:
- Watch the fleet do useful work (pick up tasks, deliver them, avoid collisions, recharge)
- **Inject disturbances live** (drop an obstacle, black out Wi-Fi in a zone, fail a robot, kill the dashboard itself) and watch the fleet route around the problem, to *prove* the decentralised claim
- **Compare** the "smart" 5-layer stack against a naive stop-and-wait baseline side-by-side (A/B benchmark mode), to show the coordination layers are actually worth something
- **Design custom warehouse layouts** (added later) instead of only using one hardcoded floor plan, save/reuse them
- **Export a run to video** for presentations

### Who uses it
A single operator/presenter, live, during a demo or a dev/test session — not a multi-user production tool. There's no login, no per-user accounts; one shared session serves whoever's connected.

## 2. The core problem driving this redesign request

The UI grew feature-by-feature over several rounds of work (base dashboard → benchmark mode → custom layout editor → saved layouts → fleet log), and every new feature added its own row of buttons to a flat top toolbar. **Nothing was ever removed or reorganized** — it's now ~6 toolbar groups plus a second conditional toolbar plus a table of saved-layout row-actions, all visible as dense rows of small buttons with terse labels. A first-time user has no way to tell, just by looking, which buttons are for **one-time setup**, which are for **routine running**, which are **destructive/hard to undo**, and which only matter in a **rare, specific mode** (editing a layout, running a benchmark).

**The goal for the redesign: same functionality, radically easier to find and understand** — better grouping, progressive disclosure (don't show editor-only controls unless editing), clearer labels/icons, and a visual hierarchy that separates "glance at this" from "click this."

## 3. Full inventory of every control that exists today

### Top bar (always visible, not interactive except the KPI numbers which are read-only)
| Element | What it shows |
|---|---|
| KPI strip | Robots, Active Tasks, Completed, Avg Time, Conflicts, Collisions Avoided — live numbers, no clicks |
| Connection indicator | "connected"/"reconnecting…" dot for the WebSocket |
| Clock + sim time | Wall clock + simulated elapsed time (`t = X.Xs`) |

### Toolbar group: **Configure**
| Control | Type | Action |
|---|---|---|
| Robots | number input (1–6) | Fleet size for the next reset |
| Tasks | number input (1–20) | Number of delivery jobs to generate |
| Seed | number input | RNG seed — same seed + same settings = same run, for repeatability |
| **Apply & Reset** | button | Sends `{n_robots, n_tasks, seed}` to the server, tears down and rebuilds the whole simulation from scratch. **Destructive** — loses the current run's progress. |

### Toolbar group: **Run**
| Control | Type | Action |
|---|---|---|
| **Start / Pause** | toggle button | Starts or pauses the tick loop (label changes between the two states) |
| **Step** | button | Advances exactly one tick while paused — for careful frame-by-frame inspection |
| **Reset** | button | Rebuilds the simulation using the *current* config values (no dialog, immediate) |
| 0.5× / 1× / 2× / 4× | segmented buttons | Playback speed multiplier |

### Toolbar group: **Inject** (live disturbances — the "prove it's decentralised" tools)
| Control | Type | Action |
|---|---|---|
| **Drop Box** | arm-then-click button | Arms box-drop mode; next click or drag-rectangle on the map drops an obstacle there. Forces D\* Lite to replan. |
| **Clear Boxes** | button | Removes all dropped obstacles |
| **Dead Zone** | arm-then-drag button | Arms dead-zone mode; drag a rectangle on the map to create a Wi-Fi blackout area — robots inside lose the mesh and fall back to local-only sensing |
| **Clear Zones** | button | Removes all dead zones |
| Robot select | dropdown | Picks which robot the next Fail/Recover applies to |
| **Fail** | button | Marks the selected robot as faulted — its task gets re-auctioned to another robot |
| **Recover** | button | Brings a failed robot back online |
| **Kill Dashboard** | button (danger-styled) | Simulates the central dashboard dying — the fleet keeps running (the whole point of "decentralised"); a banner shows on the map |

### Toolbar group: **Benchmark**
| Control | Type | Action |
|---|---|---|
| A/B vs stop-and-wait | checkbox | Turns on a side-by-side comparison: the same scenario run twice, once with the real 5-layer stack, once with a naive stop-and-wait baseline. **Restarts the current run** when toggled. Reveals a second map panel + a scoreboard panel elsewhere on the page when on. |

### Toolbar group: **Video**
| Control | Type | Action |
|---|---|---|
| **Export MP4** | button | Renders the buffered run into a downloadable video (server-side, via matplotlib/ffmpeg) |

### Toolbar group: **Layout**
| Control | Type | Action |
|---|---|---|
| **Edit Layout** | toggle button | Enters/exits the custom-layout painting mode (reveals the second "Tool/Editor" toolbar below and changes the map into an editable canvas) |
| **Reset to Default** | button | Discards any custom layout and returns to the built-in default warehouse floor plan |

### Second toolbar: **Tool** + **Editor** (only visible while editing a layout)
| Control | Type | Action |
|---|---|---|
| Rack / Pickup / Dropoff / Charger / Depot / Erase | segmented buttons | Selects what the next click/drag paints onto the grid |
| Live counts hint | text | Shows how many of each cell type are currently painted |
| **Validate** | button | Server-side checks the painted layout (bounds, no overlaps, every station reachable) and lists any problems |
| **Apply Layout** | button (primary) | Validates, then swaps the running simulation onto this layout immediately |
| **Clear Canvas** | button | Wipes the in-progress painting (confirmation dialog) |
| **Cancel** | button | Exits the editor, discarding unsaved changes (confirmation dialog) |

### Panel: **Layout Editor — issues** (only visible after Validate/Apply finds problems)
A list of validation error messages — no buttons, just readout.

### Panel: **Saved Layouts** (always visible)
| Control | Type | Action |
|---|---|---|
| **Save Current Layout As…** | button | One-click: names and saves *whatever's currently running* (default or custom) to the library — usable even outside the editor |
| Layout name input + **Save As…** | text input + button | Only visible while editing — saves the in-progress painted buffer under a new name |
| Per-row: **Load** | button | Loads that saved layout into the editor for further editing (warns if you have unsaved edits) |
| Per-row: **Apply** | button | Applies that saved layout straight to the running simulation, no editor involved |
| Per-row: **Rename** | button | Prompts for a new name |
| Per-row: **Delete** | button (danger-styled) | Removes it from the library (confirmation dialog; safe even if it's the currently-running layout) |

### Fleet Map panel
| Control | Type | Action |
|---|---|---|
| Congestion checkbox | checkbox | Toggles a heat-map overlay showing traffic density |
| The map canvas itself | click/drag surface | Doubles as: normal viewing, obstacle/dead-zone placement target (when armed), and the layout painting canvas (when editing) |
| Legend | read-only | Explains the color coding for robot states and station types |

### Panel: **Algorithm Activity** — read-only live counters, no controls (D\* Lite replans, MD-PIBT pushes, robots avoiding, mesh online/lost, near-misses, last auction)

### Panel: **Replay & Video**
| Control | Type | Action |
|---|---|---|
| **Play/Pause** | button | Plays back the buffered run from the scrub position |
| Scrub bar | slider | Jump to any point in the buffered history |
| **● LIVE** | button | Snap back to watching the live simulation |
| Export progress bar | read-only | Shown while an MP4 export is rendering |
| Video player + download link | appears after export | Watch/download the rendered MP4 |

### Panel: **Fleet Summary** (footer, read-only) — utilisation, battery, and per-status robot counts, no controls

### Panel: **Robot Status** (read-only cards, one per robot) and **Fleet Log** (read-only structured per-robot telemetry blocks) — both display-only, covered for completeness since they're dense with information even though they have no buttons.

## 4. What's *not* to change (constraints for the redesign agent)

- **The backend/API and WebSocket contract must stay the same** — this doc is only about *presentation*. Every control above maps to a specific existing REST endpoint or client-side-only state toggle (`POST /api/control`, `POST /api/event`, `POST /api/layout*`, `POST /api/layouts*`, etc. — see `server.py`). A redesign should re-skin/reorganize, not require new backend work, unless explicitly agreed.
- **Nothing here needs new functionality** — the ask is discoverability and clarity, not new features.

## 5. Suggested angle for the redesign agent (not prescriptive, just framing)

Group by **frequency + risk**, not by "which feature added it":
- **Always-visible, low-risk, frequent**: Start/Pause/Step/Speed, Congestion toggle, Replay controls
- **Occasional setup, before a run**: Configure (robots/tasks/seed), Layout selection/editing
- **Deliberate/rare, demo-specific**: Inject disturbances, Benchmark toggle, Export
- **Destructive or hard to undo**: Apply & Reset, Kill Dashboard, Delete layout, Clear Canvas — should look and feel distinctly different from routine buttons
- **Progressive disclosure**: the entire Tool/Editor toolbar and Saved-Layouts Save-As row already only appear in edit mode — that pattern should probably extend further (e.g. Inject tools could collapse until intentionally opened)
