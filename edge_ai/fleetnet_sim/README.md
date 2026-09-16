# FleetNet Multi-Robot Simulation & Telemetry

Drives the **real** `Fleet_SIH/core` algorithms (D* Lite, NH-ORCA, CBBA/
ED-CBBA, Karma+MD-PIBT, real/in-process comms — never reimplemented) over
warehouses produced by `warehouse_layout`'s `fleetnet_layout` generator, and
persists complete, traceable telemetry to PostgreSQL/TimescaleDB so ML
datasets can later be built from the database alone, without rerunning
simulations.

This is the **thin-slice** pass of the full 24-section spec: correct end
to end, reduced in breadth. See "Known limitations" below for exactly
what's deferred.

## Install

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"    # dev extra includes scikit-learn for model training
docker compose up -d          # starts TimescaleDB on localhost:5432
```

`Fleet_SIH` must be a sibling directory of this package (as it already
is) — `fleetnet_sim/_paths.py` bootstraps `Fleet_SIH/core` onto
`sys.path` automatically; set `FLEET_SIH_ROOT` if your checkout is laid
out differently. `warehouse_layout` lives nested at
`fleetnet_sim/warehouse_layout/` and is installed as an editable
dependency straight from there (see `pyproject.toml`).

## Quick start

```bash
# One run against an already-generated layout:
.venv/bin/python -m fleetnet_sim simulate \
    --layout warehouse_layout/outputs/layouts/2_medium_grid.json \
    --robots 15 --seed 1 --duration 300 --arrival-rate 0.5

# Inspect it later:
.venv/bin/python -m fleetnet_sim inspect-run --run-id <run_id from above>

# Build an ML dataset from one or more runs (comma-separated run_ids):
.venv/bin/python -m fleetnet_sim export-dataset --model eta --run-ids <run_id>
.venv/bin/python -m fleetnet_sim export-dataset --model conflict --run-ids <run_id> --horizon 2.0

# Many runs (layouts x seeds x robot counts) in one command, for a real
# training corpus — every layout in a directory, 2 seeds, 2 fleet sizes:
.venv/bin/python -m fleetnet_sim batch \
    --layouts warehouse_layout/outputs/layouts \
    --seeds 0-9 --robots 10,15,20 \
    --duration 300 --arrival-rate 0.6 \
    --export-datasets eta,conflict,congestion
# Writes outputs/batch_runs/summary.json (per-run status/metrics) and,
# with --export-datasets, builds each dataset once from every completed
# run_id in the batch (not one dataset per run). A failed individual run
# is recorded with status="failed" and does not abort the rest of the
# batch.

# Named scenario presets instead of hand-picking flags every time (see
# "Scenario presets" below) — a single flag replaces --robots/
# --arrival-rate/--duration, and any of those still override one field:
.venv/bin/python -m fleetnet_sim simulate --layout <path> --preset dense
.venv/bin/python -m fleetnet_sim batch --layouts <dir> --seeds 0-4 --robots 10,15,20 --preset congestion_corpus
```

Run tests (the DB-dependent ones auto-skip if `docker compose up -d`
hasn't been run):

```bash
.venv/bin/pytest -q
```

Tests write to a separate `fleetnet_sim_test` database (auto-created on
the same TimescaleDB instance the first time it's needed — see
`tests/conftest.py`'s `TEST_DSN`/`_ensure_test_db_exists`), never the
real `fleetnet_sim` database `simulate`/`batch`/etc. use. This was a real
issue caught in a later pass: every test file used to hardcode the real
DSN, so 310 rows of test junk had silently accumulated in the "real"
database over the course of this project's own development before it
was noticed and fixed. `fleetnet_sim_test` is disposable and grows with
every test run — feel free to drop and let it be recreated.

Prefer a browser to the terminal? `.venv/bin/python -m fleetnet_sim
dashboard` opens a local web UI for everything above — see "Dashboard"
below.

## Architecture

```
layout JSON ──▶ integration.world_bridge.build_world_bridge()
                    │  rasterizes racks/columns/exclusions into a
                    │  core.world.World grid (1 cell = 1m); aisles/zones
                    │  stay free space, so a wide aisle becomes several
                    │  parallel free columns — two robots can be planned
                    │  into adjacent cells and pass side by side.
                    ▼
core.fleet_manager.spawn_fleet()  ──▶  core.engine.Engine
                                          │  reproduces fleet_sim.py's exact
                                          │  per-tick order: CBBA.step_tick()
                                          │  → task FSM → ConflictResolver.resolve()
                                          │  → NH-ORCA + D* Lite motion → collisions
                                          ▼
                              telemetry.collector.TelemetryCollector
                                          │  (on_algorithm_event / on_task_event /
                                          │   on_robot_sample / on_comm_event hooks)
                                          ▼
                          storage.repository.BufferedRepository ──▶ TimescaleDB
                                          │
                                          ▼
        datasets.eta_builder / conflict_builder / congestion_builder ──▶ Parquet
```

Every algorithm concern is a thin **adapter** around the real
`Fleet_SIH/core` API — see `integration/` — never a reimplementation:

| Concern | Real implementation | Adapter |
|---|---|---|
| Global planning | `core.planner.dstar_lite.DStarLite` | `core/robot_agent.py` (start_route_to/refresh_plan), fed by `integration/world_bridge.py`'s grid |
| Local avoidance | `core.avoidance.nh_orca.nh_orca_velocity` | `core/engine.py::_step_motion` |
| Task allocation | `core.allocation.cbba.CBBAAgent` | `integration/cbba_adapter.py` |
| Conflict/priority | `core.conflict.mdpibt.ConflictResolver` + `karma.KarmaLedger` | `integration/conflict_adapter.py` |
| Communication | `core.comms.inprocess.InProcessBus` / `core.comms.zenoh_bus.ZenohBus` | `integration/comms_adapter.py` |

`fleetnet_sim/config/timing.py` documents exactly which fleet_sim
constants are tick-counts recalibrated for our configurable `dt` (only
`ConflictResolver.decision_hold_ticks` and CBBA's
`anti_entropy_interval` — everything else fleet_sim already expresses
in seconds and is used unchanged).

## Database

Implemented: `experiments`, `simulation_runs`, `warehouses`, `robots`,
`tasks` (lifecycle-summary, one row per robot/task written at run end),
`robot_state_ts` (sampled, TimescaleDB hypertable), `algorithm_events`
(every CBBA/D* Lite/Karma+MD-PIBT/communication event — hypertable),
`route_events` (hypertable), `task_lifecycle_events`, `run_metrics`,
`model_dataset_registry`.

**Breadth-phase addition:** `edge_state_ts`/`node_state_ts`/`zone_state_ts`
(hypertables) — continuous occupancy/speed time series, sampled at the
same cadence as `robot_state_ts` by grouping that tick's robot samples by
each robot's *nearest* edge/node/zone (`WorldBridge.nearest_edge`/
`nearest_node_id`/`cell_to_zone`). This is what makes the Congestion
Predictor dataset buildable (see below) — a wide aisle rasterized into
several free cell-columns now shows up as one edge's `occupancy_count`
climbing past 1 when two robots actually pass side by side, which is the
concrete signal the width-aware bridge was built to make observable.

**Now promoted:** `conflict_events` (one row per `(yielder, winner)` pair
per tick — same real `ConflictResolver.dependency_edges` ground truth,
now directly queryable instead of parsed out of JSONB), `congestion_events`
(one row per committed congestion-detour attempt), and
`communication_events` (one row per `MessageBus.publish` call).
Conflict/congestion promotion is *additive* — the raw `algorithm_events`
audit row (with `should_yield`/positions context, or replan/path-cost
detail) is still written too, and a test
(`test_conflict_events_mirror_dependency_edges_in_algorithm_events`)
asserts the promoted count exactly matches the audit trail. Communication
promotion *replaces* the old JSONB write entirely — it fired on every
single publish (CBBA's bid cascades make it the highest-volume event type
by far) and nothing read it out of `algorithm_events` for datasets, so
folding it into the generic JSONB table was pure bloat.
`datasets/conflict_builder.py` and `replay/loader.py` now both read
`conflict_events`/`congestion_events` directly instead of parsing JSONB.

## ML datasets

- **`eta`** — fully implemented (`datasets/eta_builder.py`). One row per
  sampled robot-en-route observation; label = actual remaining time to
  task completion. Programmatically asserts `completion_time >
  simulation_time` for every row (no future leakage).
- **`conflict`** — fully implemented (`datasets/conflict_builder.py`).
  Ground truth is the *real* `ConflictResolver.dependency_edges` output
  (captured verbatim per tick), not a derived proxy — a `(yielder,
  winner)` edge at time t is an actual already-arbitrated conflict from
  the real Karma/MD-PIBT implementation. Label = does this exact pair
  conflict again within the configured horizon after the observation.
- **`congestion`** — fully implemented (`datasets/congestion_builder.py`).
  One row per sampled `(edge, tick)` observation from `edge_state_ts`.
  Label = does this exact edge's `occupancy_count` reach
  `congestion_occupancy_threshold` (default 2) or more simultaneous
  robots within `horizon_s` (default 5s) strictly after the observation
  — derived directly from real occupancy telemetry, not a proxy model.

Splits are **by run_id** (`datasets/splits.py`), never by row — a run's
telemetry never crosses train/val/test, per Section 19.

## Baseline models (`fleetnet_sim/models/`)

Each of the three datasets above has a baseline trainer, so the pipeline
runs all the way from simulation to a trained, held-out-evaluated model:

- **`eta`** (`models/eta_model.py`) — `GradientBoostingRegressor` over
  numeric features (age since release, position, speed, remaining
  distance, replan count, local density, priority) + one-hot-encoded
  zone/task-type. Evaluated by MAE/RMSE/R² on train/val/test.
- **`conflict`** (`models/conflict_model.py`) — `RandomForestClassifier`
  (`class_weight="balanced"`, since real conflicts are rare) over
  relative kinematics (distance, heading difference, speeds, closing
  speed, same-task, replan counts). Evaluated by accuracy/precision/
  recall/F1/ROC-AUC.
- **`congestion`** (`models/congestion_model.py`) — `RandomForestClassifier`
  over an edge's current occupancy/speed/occupancy-delta.

All three deliberately exclude identifier columns (`run_id`/`robot_id`/
`task_id`/`edge_source`/`edge_target`) from the feature set even though
the dataset schema sidecars list them — those exist for traceability/
joins, not because an ID from one run generalizes to another. Every
trained model is registered in `trained_model_registry`, pointing back
at the exact `dataset_id` (and hence the exact `run_ids`/telemetry) that
produced it — same traceability discipline as `model_dataset_registry`.

```bash
.venv/bin/python -m fleetnet_sim train-model --model eta --dataset-id <dataset_id>
.venv/bin/python -m fleetnet_sim train-model --model conflict --dataset-path outputs/datasets/conflict_xxxx.parquet
```

**Real results** (105-run batch: all 7 generated layouts × 5 seeds × 3
fleet sizes, ~310k/598k/229k rows respectively), evaluated on a held-out
*set of runs* the model never trained on:

| Model | Test metric | Value |
|---|---|---|
| eta | MAE | 12.5s (R²=0.24) |
| conflict | ROC-AUC / recall | 0.98 / 0.95 |
| congestion | ROC-AUC / accuracy | 0.94 / 0.92 |

The ETA baseline is the weakest of the three (expected — remaining time
to task completion depends on downstream congestion/replanning the
observation-time features only partially capture); conflict and
congestion both show strong, non-degenerate signal from real telemetry.
These are baselines proving the full loop works honestly end to end, not
tuned final models.

## Inference (`fleetnet_sim/models/inference.py`)

Closes the ML lifecycle loop the whole pipeline was built for:
`simulate` → telemetry → dataset → `train-model` → **`predict`**. Scores
one *snapshot* — one tick of a stored run — using only telemetry that
existed at or before that tick, never anything later (the same
no-future-leakage discipline the dataset builders enforce). This is
offline validation ("if this model had been live at tick X, what would
it have said"), not a true live/streaming predictor — that would need
the engine to call out mid-tick, which is future work.

```bash
.venv/bin/python -m fleetnet_sim predict --model-id <model_id> --run-id <run_id>
# --model-path <path.joblib> --model-name eta|conflict|congestion instead
# of --model-id if the model isn't in trained_model_registry.
# --at-tick <tick> to score a specific historical instant (default: the
# run's latest tick with relevant data). --output <path.csv> for the
# full predictions; --pair-radius for the conflict model.
```

Feature construction here deliberately mirrors rather than imports from
the dataset builders — those build historical *labeled* datasets over a
whole run's grouped telemetry; this needs one unlabeled snapshot at a
single tick, and threading an "as-of" cutoff through every builder's
grouped-aggregation logic for one call site would be more churn than the
small amount of duplicated feature math. One real fix during
verification: the ETA model's `GradientBoostingRegressor` has no
non-negativity constraint and produced a real negative prediction
(-3.5s) during testing — clipped at 0 in `predict_eta_snapshot`, since a
negative remaining time is never physically meaningful (a light
post-processing step, not a change to the model or a way of hiding its
honestly-reported baseline-level accuracy).

## Replay (`fleetnet_sim/replay/`)

Renders a stored run as an animated GIF, built entirely from stored
telemetry (never reruns the simulation):

```bash
.venv/bin/python -m fleetnet_sim replay --run-id <run_id> --output outputs/replays/run.gif
# Options: --fps, --trail (fading-trail length), --start-time/--end-time
# (seconds into the run), --show-graph (overlay the navigation graph)
```

- The warehouse background is drawn by reusing `fleetnet_layout`'s own
  renderer (`draw_layout_static`, extracted from its `render_layout` so
  it can draw onto an existing `Axes` instead of only saving a static
  PNG) — the exact geometry the run actually used, not re-derived.
- Robots are colored by task state (`TO_PICKUP`/`PICKING`/`TO_DROPOFF`/
  `DROPPING`/`IDLE`) with a short fading trail.
- Active conflicts are drawn as a gold line between the two robots
  involved — sourced from the same real `ConflictResolver.dependency_edges`
  ground truth the Conflict Predictor dataset uses, not a derived proxy.
  Congestion-detour events are marked with a star.
- Algorithm events fire every tick but `robot_state_ts` is subsampled
  (`TelemetryConfig.robot_state_sample_every_n_ticks`), so each event is
  bucketed onto its nearest actually-sampled tick (`loader.py`'s
  `_nearest_tick`) — verified by a real bug this caught: an earlier
  version returned the *index* into the tick list instead of the tick
  value itself, which happened to look correct in a manual visual check
  (the run's ticks were a contiguous multiple-of-5 sequence from 0, so
  index scaling coincidentally lined up) but was wrong in general; a
  dedicated test with a less-regular tick range caught the mismatch, and
  the fix is regression-tested in `tests/test_replay.py`.

## Scenario presets (`fleetnet_sim/scenarios/presets.py`)

Named fleet+task bundles, same pattern as `warehouse_layout`'s own
`config/presets.py` (a name resolves to config, still going through
normal validation — never hand-authored). These are the *simulation*
half of a scenario; `warehouse_layout`'s presets are the *warehouse*
half, and the two compose independently:

| Preset | Robots | Arrival rate | Duration | Tuned for |
|---|---|---|---|---|
| `sparse` | 6 | 0.3/s | 300s | Low-traffic control/baseline scenario |
| `dense` | 25 | 1.5/s | 300s | Stress test — the density range where the CBBA livelock and rare collisions were actually found |
| `bottleneck_stress` | 18 | 1.2/s | 300s | Pair with a `warehouse_layout --preset bottleneck_heavy` layout |
| `eta_corpus` | 12 | 0.6/s | 300s | ETA Predictor dataset generation |
| `conflict_corpus` | 20 | 1.0/s | 240s | Conflict Predictor dataset generation |
| `congestion_corpus` | 15 | 0.8/s | 180s | Congestion Predictor dataset generation — the exact mix used in this project's own 105-run training batch |

`--preset` works on both `simulate` and `batch`; any of `--robots`/
`--dt`/`--duration`/`--arrival-rate` passed alongside it overrides just
that one field (e.g. `--preset dense --robots 30`). On `batch`,
`--robots` is always the swept sweep-axis — the preset supplies
tasks/algorithms/dt/duration, never the fleet size, since sweeping fleet
size is exactly what `batch --robots` is for.

## Dashboard (`fleetnet_sim/dashboard/`)

A local web dashboard for browsing layouts, launching simulations, and
watching them work — everything the CLI does, but visual instead of
static PNGs/GIFs and stdout metrics.

```bash
.venv/bin/python -m fleetnet_sim dashboard
# Options: --host --port (default 127.0.0.1:8765) --dsn --layouts-dir
# (repeatable; default: warehouse_layout/outputs/layouts and
# .../layouts_batch) --no-browser
```

It's a small FastAPI backend (`app.py`/`routes_*.py`/`jobs.py`) serving
a plain HTML/JS/canvas frontend (`static/`, no build step, no npm) —
explicitly a **local tool you run yourself**, not a hosted page, because
it needs to reach your local Postgres and launch real local Python
simulations, neither of which a hosted page can do.

- **Layouts tab**: browse every generated layout (from the configured
  directories), rendered on canvas by reimplementing
  `fleetnet_layout/visualization/renderer.py`'s exact color tables and
  z-order in JS (`static/js/layoutRenderer.js`) — there's no way to
  share the Python/matplotlib renderer with a browser, so this is a
  from-scratch but faithful port.
- **Launch tab**: pick a layout + a preset (or custom robots/dt/
  duration/arrival-rate/seed), launches the exact same
  `_run_simulation` function `simulate`/`batch` use — reused, not
  reimplemented — in a background thread so the server stays responsive.
- **Watch tab**: live playback *while a simulation is still running*,
  and post-hoc replay afterward, through **one** polling endpoint
  (`GET /api/runs/{id}/frames?since_tick=`) — the only difference
  between "live" and "replay" is whether the response's `run_status` is
  `"running"` or terminal. Simulations already run faster than real
  time (dashboard-launched runs use a smaller `flush_batch_size=25` so
  telemetry is visible to the poll loop promptly), so watching a run
  live is genuinely watching it happen, just fast-forwarded rather than
  throttled to match wall-clock — throttling the engine was considered
  and rejected because it would require a second, dashboard-only
  code path for running a simulation.
- **Run History tab**: past runs with metrics, click straight into
  replay.

The dashboard writes to the **same real `fleetnet_sim` database**
`simulate`/`batch` use (never the isolated `fleetnet_sim_test` tests
use) — this is asserted by a dedicated grep check (no `TEST_DSN`
reference anywhere under `dashboard/`) given this project already made
and fixed exactly that mistake once (see "Verified this pass — final
check" below).

## Known limitations

- **Congestion detour** — `fleet_sim`'s phantom-obstacle scratch-`World`
  re-route is now ported verbatim (`core/engine.py::_attempt_congestion_detour`,
  gated by `AlgorithmsConfig.enable_congestion_detour`, logged as an
  `algorithm_events` row with `trigger="congestion_detour"`). It fires
  when a robot's velocity stays under `JAM_SPEED_THRESH` for
  `CONGESTION_TIMEOUT_S` (1.2s) — genuinely stalled/gridlocked robots —
  and only commits to a route that's a real alternative
  (`DETOUR_MAX_COST_RATIO`-bounded), never through a real static
  obstacle (regression-tested). It does **not** address every collision:
  `run_metrics.safety.collision_count` can still show a rare, brief
  (sub-second) overlap between two robots converging faster than NH-ORCA
  fully resolves — that's a transient that clears before the 1.2s
  stall threshold is ever reached, the same NH-ORCA-density limitation
  `fleet_sim.py` itself has, not a gap introduced by this port (verified
  by A/B seed comparison: enabling/disabling the detour made no
  difference to that specific collision's occurrence, and instrumented
  timing showed 0 detour attempts around it — it wasn't a stall).
  It's exactly the kind of event the Conflict Predictor dataset is meant
  to help predict *ahead of time* once a model is trained on it.
- **Real `ZenohBus`** is wired and selectable via
  `CommunicationConfig.backend`, but `InProcessBus` is the default for
  batch ML-data-generation runs (per the chosen scope).
- **Replay/visualization** and a **scenario-preset library** (Section
  15) are now both built (see above) — the preset library covers the
  simulation side (fleet/task presets); `warehouse_layout`'s own
  presets remain the only ones for layout shape.
- `robots`/`tasks` are lifecycle-*summary* tables (final state at run
  end), not per-tick time series — the per-instant trail for a robot is
  `robot_state_ts`; for a task it's `task_lifecycle_events`.
- **Fixed**: the `RecursionError` seen on one combination in the 105-run
  batch (`6_irregular.json`, seed 1, 20 robots) was root-caused and
  mitigated. It's a real livelock in `Fleet_SIH`'s own CBBA/comms
  interaction — `InProcessBus.publish` dispatches every subscriber
  synchronously and recursively, and confirmed via direct reproduction,
  two agents (`robot_4`/`robot_5`) can get into a bid tie that
  ping-pongs between exactly those two agents forever (raising Python's
  recursion limit to 1,000,000 just hangs instead of erroring, proving
  it's a genuine unbounded livelock, not merely deep recursion). Since
  `Fleet_SIH` is never modified, the fix is a circuit breaker on our
  side: `core/engine.py::_safe_announce` catches the `RecursionError`,
  logs it as a real (`success: False`) `algorithm_events` row with
  `trigger="announce_livelock"`, fails only that one task (retrying the
  identical announce would almost certainly hit the identical
  deterministic tie again), and lets the simulation keep running.
  Re-run on the exact failing scenario: completes all 1800 ticks, catches
  the livelock once, 79 tasks still complete normally. Regression-tested
  in `tests/test_engine.py::test_cbba_announce_livelock_is_caught_not_fatal`.
- **Dashboard**: no authentication (binds `127.0.0.1` by default — a
  local single-user tool); the in-memory `JobRegistry` doesn't survive a
  server restart (`simulation_runs.status` in Postgres is the real
  source of truth; the registry is only a low-latency cache for actively
  tracked jobs); no websockets/push, polling only (sufficient given runs
  finish in seconds); no dataset/training/prediction UI (stays CLI-only,
  out of scope for this pass); no layout-generation UI (browsing only).

## Verified this pass (final check — ready for future data prep/simulation)

- **Found and fixed a real hygiene bug**: every test file hardcoded the
  real `fleetnet_sim` DSN and never cleaned up after itself, leaving 310
  accumulated `test_*`/`demo_*` rows in the database meant for genuine
  work. Fixed by centralizing a separate `TEST_DSN` (pointing at
  `fleetnet_sim_test`) in `tests/conftest.py`, auto-created if missing,
  and updating all 6 DB-backed test files to use it. Verified the fix
  directly: a full `pytest -q` run added zero rows to `fleetnet_sim`
  while writing 34 rows to `fleetnet_sim_test`.
- Purged all accumulated test/demo/verification data from the real
  `fleetnet_sim` database (`TRUNCATE ... RESTART IDENTITY CASCADE`
  across all 18 tables) and confirmed all 9 hypertables survived intact
  (`timescaledb_information.hypertables`). Removed orphaned dataset
  files from `outputs/datasets/` left over from earlier passes.
- Ran one final, complete pipeline end to end against the now-clean
  database to confirm every command still works together: `batch` (42
  runs: all 7 layouts × 3 seeds × 2 fleet sizes, `--preset
  congestion_corpus`, 0 failed) → `export-dataset` (all 3 models,
  108k/170k/86k rows) → `train-model` (all 3, consistent with earlier
  passes: ETA MAE ~11.6s, conflict ROC-AUC 0.98, congestion ROC-AUC
  0.94) → `predict` (all 3 — including a real, sensible catch: two
  robots 1.1m apart scored a 0.97 conflict probability) →
  `inspect-run` → `replay`. Cleaned up afterward, leaving `fleetnet_sim`
  empty and schema-correct.
- Re-confirmed `warehouse_layout` (38/38) and `Fleet_SIH` (git working
  tree clean) remain fully untouched by this entire project.

## Verified this pass (inference)

- 53/53 tests pass — 7 new in `tests/test_inference.py`, training real
  models on a 3-run split-balanced fixture then scoring snapshots from
  them (shape, probability-range, and non-negativity checks; `--at-tick`
  confirmed to select the exact requested `simulation_time`, not just
  "some" tick).
- Real end-to-end CLI run, not just unit tests: `simulate` (3 seeds) →
  `export-dataset` (all 3 models) → `train-model` (all 3) → `predict`
  against a real trained `eta_model_a799e1d3cfea`/
  `conflict_model_773b814124ac`/`congestion_model_351e4283cf4f` on live
  telemetry from `infer_smoke_0`, producing real, sane predictions for
  all three model types (e.g. `robot_2` predicted 5.6s remaining vs.
  `robot_4` at -3.5s before the clip fix above — the actual bug that
  fix addresses, caught by hands-on verification, not a unit test).
- CLI error handling verified: an unknown `--model-id` now prints a
  clean one-line error and exits 1, not a raw Python traceback.

## Verified this pass (dedicated event tables)

- 46/46 tests pass — 3 new in `tests/test_storage_integrity.py`:
  communication events land only in `communication_events` (zero leak
  into `algorithm_events`), `conflict_events`' row count exactly matches
  the sum of `dependency_edges` across the still-written
  `algorithm_events` audit rows (proving the promotion is additive and
  faithful, not a lossy rewrite), and `congestion_events` actually
  populates under the same dense scenario `test_engine.py`'s
  congestion-detour test relies on.
- Real end-to-end run (`6_irregular.json`, 20 robots,
  `--preset conflict_corpus`): 447 `conflict_events` rows, 1
  `congestion_events` row, 2684 `communication_events` rows, and
  confirmed **zero** `algorithm_events` rows with
  `algorithm_name='communication'` (the old path, now fully replaced).
  `export-dataset --model conflict` and `replay` both re-verified against
  the new tables on this same real run — the conflict overlay in the
  rendered GIF still lines up exactly with a direct DB query, same as
  the replay phase's own verification.

## Verified this pass (dashboard)

- 62/62 tests pass — 9 new in `tests/test_dashboard.py` using FastAPI's
  `TestClient` against the isolated test database: layout listing/detail
  (incl. 404 on an unknown id), full launch→poll→completed→run-detail→
  frames lifecycle, unknown-preset returns 422, unknown-layout returns
  404, and a dedicated regression guard asserting incremental paging
  (`since_tick` advancing page to page) never returns an
  already-seen tick — the exact bug class a naive
  re-fetch-everything-every-poll approach would hide.
- Real, hands-on end-to-end verification, not just automated tests:
  started the actual server (`python -m fleetnet_sim dashboard`),
  confirmed `GET /api/layouts` lists all 107 real generated layout files
  with correct metadata, fetched a real layout's full JSON and confirmed
  its shape, launched a real `sparse` simulation via `POST /api/simulate`
  and confirmed it completed and is queryable via `GET /api/runs`.
  Launched a real `dense` (25-robot) simulation and, while it was still
  running, polled `GET /api/runs/{id}/frames` repeatedly and watched
  `last_tick` genuinely advance tick by tick (705 → 715 → 740 → … → 985
  across successive ~0.3s-apart polls) — direct proof the live-playback
  design actually works, not just that the endpoint returns data.
  Confirmed the completed run's telemetry contains real conflict edges
  (551 of 599 frames) and congestion-detour markers (43 frames), matching
  the run's own `collision_count: 16`/`total_replans: 339` metrics.
- Confirmed dashboard-launched runs land in the real `fleetnet_sim`
  database (`grep -rn "TEST_DSN" dashboard/` → zero matches) and cleaned
  up all dashboard-launched verification runs afterward.
- Full existing 53-test suite still passes unmodified.

## Verified this pass (scenario presets)

- 43/43 tests pass — 8 new in `tests/test_scenario_presets.py` (every
  preset has a valid config, unknown-preset raises, resolution logic
  correctly layers preset → explicit-flag-override, batch's fleet-size
  sweep always wins over the preset's own robot_count).
- Real CLI runs, not just unit tests: `simulate --preset sparse`
  produced `robot_count=6`/`duration_s=300`/`arrival_rate=0.3` exactly
  as specified; `--preset sparse --robots 3` correctly overrode only the
  robot count; `batch --robots 10,15 --preset bottleneck_stress`
  produced runs with `arrival_rate_per_s=1.2` (from the preset) while
  `robot_count` came from `--robots`, not the preset's 18 — confirmed by
  querying the stored `config_json` directly, not just trusting the CLI
  output.

## Verified this pass (replay)

- 35/35 tests pass — 4 new in `tests/test_replay.py`. Real GIFs rendered
  from two real generated layouts (`2_medium_grid.json`, 12 robots;
  `6_irregular.json`, 20 robots) and visually inspected frame-by-frame,
  which is how the `_nearest_tick` index/value bug above was actually
  caught and confirmed fixed (before vs. after: a conflict shown at the
  wrong simulation instant vs. the gold line appearing exactly at the
  real event's `t=27.5s`/`tick=275`, matching a direct DB query).
- `warehouse_layout`'s `render_layout` was refactored (extracted
  `draw_layout_static`) without changing its own behavior — its 38 tests
  still pass unmodified after the refactor.

## Verified this pass (model training)

- 30/30 tests pass (`pytest -q`, TimescaleDB running) — 6 new tests in
  `tests/test_models.py` cover all three trainers plus
  `models/common.py`'s dataset resolution/split-loading, using three
  deliberately-chosen run_ids (one per split bucket, via `split_for_run`)
  so train/val/test are all genuinely non-empty rather than degenerate.
- Real batch: 105 runs (all 7 generated layouts × 5 seeds × 3 fleet
  sizes, 180s each) → 3 combined datasets (311k/598k/229k rows) → 3
  trained baseline models, all evaluated on held-out runs (see "Baseline
  models" above for the actual numbers). 104/105 runs completed; 1 hit
  the CBBA announce-livelock `RecursionError` mid-run (caught by
  `batch`'s per-run failure isolation, did not abort the rest) — since
  root-caused and fixed with a circuit breaker, see Known Limitations.
- `warehouse_layout`'s own 38 tests still pass unmodified; `Fleet_SIH`'s
  git working tree remains untouched.

### Prior pass (breadth phase)

- 20/20 tests passed: engine correctness (no collisions/no
  motion-on-blocked-cell/reproducible-for-same-seed, edge/node/zone
  occupancy samples emitted and shared across robots, congestion detour
  fires under dense load and never routes through a static obstacle),
  storage integrity, all three dataset builders' leakage checks
  (congestion's independently reconstructs its label from raw
  `edge_state_ts` rows rather than trusting the builder's own bisect
  logic).
- Congestion detour: confirmed firing on a real layout under a 22-25
  robot stress run, and confirmed via an on/off A/B seed comparison that
  its scope is exactly what it claims to be (stalled/gridlocked robots),
  not a general collision eliminator — see Known Limitations for the
  honest characterization of what it does and doesn't fix.

### Earlier pass

- Simulated 3 different generated layouts (u_flow/grid/irregular
  archetypes) at different fleet sizes, exported a combined 3-run ETA
  dataset with a proper train/test split by run_id.
