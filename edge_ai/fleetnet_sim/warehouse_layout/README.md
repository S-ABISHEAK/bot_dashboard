# FleetNet Warehouse Layout Generator

A procedural, validated, reproducible 2D warehouse-layout generator: the
environment foundation for the FleetNet decentralized multi-robot
warehouse project. This package produces warehouse geometry + a
navigation graph + derived metrics as canonical JSON — it does **not**
implement any robot algorithm (CBBA/Karma, D* Lite, MDPiBT, NH-ORCA,
Zenoh). Those live separately in `../Fleet_SIH/` and are untouched by
this package.

See `fleetnet_warehouse_layout_research.md` and the companion "Sourced
Specification Reference" document (both in the parent directory) for
the full research spec this implementation follows.

## Install

```bash
python3.12 -m venv .venv          # 3.12 recommended; shapely/pydantic
                                   # wheel availability on very new
                                   # Python versions (e.g. 3.14) is not
                                   # guaranteed
.venv/bin/pip install -e ".[dev]"
```

## Quick start

Generate one layout (JSON + PNG render):

```bash
.venv/bin/python -m fleetnet_layout generate \
    --seed 42 --scale medium --industry ecommerce --archetype grid \
    --visualize
```

Output: `outputs/layouts/<layout_id>.json`, `outputs/renders/<layout_id>.png`.

Generate a batch of 100+ layouts with a diversity/rejection report:

```bash
.venv/bin/python -m fleetnet_layout batch --count 100 --seed 42
```

Output: `outputs/layouts/*.json`, `outputs/reports/batch_report.json`.

Inspect a stored layout's validation result:

```bash
.venv/bin/python -m fleetnet_layout validate --input outputs/layouts/<layout_id>.json
```

Use a stress-test preset instead of hand-picking parameters:

```bash
.venv/bin/python -m fleetnet_layout generate --preset bottleneck_heavy --seed 1 --visualize
```

Presets: `normal`, `high_density`, `bottleneck_heavy`, `irregular`,
`multi_zone`, `large`, `narrow_aisle`, `high_intersection` (see
`fleetnet_layout/config/presets.py`).

Run the demonstration scripts:

```bash
.venv/bin/python examples/generate_one.py
.venv/bin/python examples/generate_batch.py
.venv/bin/python examples/demo_seven_scenarios.py   # the 7 named Section-AN scenarios
```

Run tests:

```bash
.venv/bin/pytest -q
```

## Architecture

```
seed -> generation.sampling.sample_config()      # typed, distributed (non-uniform) parameter sampling
      -> generation.archetypes.<archetype>.build() # racks -> aisles -> zones -> docks -> columns
      -> graph.builder.build_navigation_graph()    # geometry -> navigation graph (exact rectangle-adjacency extraction)
      -> validation.validator.validate_layout()    # hard gate; tags failures by responsible config subsection
      -> [reject: generator.py resamples just the tagged subsection, up to 25 attempts]
      -> graph.metrics.compute_metrics()           # aisle/intersection/dead-end counts, DERIVED bottleneck candidates
      -> serialization.json_io.to_json_dict()      # canonical JSON (Section Z schema)
```

Package layout mirrors the separation of concerns above:
`config/` (schema, distributions, presets) → `generation/` (sampling +
per-archetype builders + shared storage/aisle/zone/dock/constraint
modules) → `geometry/` (Shapely-backed primitives and operations) →
`graph/` (navigation graph construction + metrics) → `validation/`
(the hard gate) → `serialization/` (JSON I/O) → `visualization/`
(Matplotlib renderer) → `diversity/` (batch reporting) → `cli/`.

## Supported parameters

The full typed schema is `fleetnet_layout/config/schema.py`, with every
field's type/units/range/FIXED-vs-SAMPLED status documented inline.
Top level: `warehouse` (seed, scale_class, industry_type, archetype,
dimensions), `structural_constraints` (columns, dock wall, fire lanes,
exclusions), `storage` (blocks, rack type/orientation, density),
`aisles` (main/secondary counts and width classes, cross-aisle
interval, one-way ratio), `zones` (8 operational zones), `constraints`
(clearance, dead-end length, connectivity/egress requirements),
`diversity_controls` (irregularity level, zone arrangement variant).

## Supported archetypes

| Archetype | Status |
|---|---|
| `grid` | Full — the base parallel-aisle grammar every other archetype builds on |
| `flow_through` | Full — two dock walls (inbound/outbound), storage between |
| `u_flow` | Full — single dock wall + a genuine perimeter loop aisle |
| `l_flow` | Partial — corner-biased zone ordering on one wall; true adjacent-wall corner geometry deferred (see module docstring) |
| `central_corridor` | Full — grid's mandatory spine relabeled as the dominant corridor, secondary aisles as feeders |
| `zone_based` | Full — 2-4 independently-parameterized sub-fields (different rack type/density each) sharing one concatenated spine |
| `fishbone` | Stub — reuses `grid`'s orthogonal geometry; true angled aisles deferred (lowest priority per the research spec) |

## Validation checks (hard gate)

Illegal overlap (rack/zone/exclusion vs. rack/zone/exclusion — aisles
are exempt by spec), boundary containment, full graph connectivity,
zone reachability (graph degree + physical aisle adjacency), minimum
clearance, dead-end segment length, one-way edge consistency, and an
opt-in dual-egress check (vertex-disjoint-paths via Menger's theorem;
off by default — see `ConstraintsConfig.require_dual_egress_paths`'s
docstring for why). A rejected layout's failures are tagged to the
config subsection most likely responsible so the generator resamples
just that subsection, not the whole layout.

## Output schema

Canonical JSON per layout: `schema_version`, `generator_version`,
`layout_id` (deterministic hash of seed+config, not random),
`parameters` (full sampled config), `warehouse` (summary dims),
`geometry` (footprint, racks, aisles, zones, columns, exclusions,
docks, fire_lanes — every object has a stable string `id`),
`navigation_graph` (networkx node-link JSON), `derived_metrics`
(counts, storage_density, `bottleneck_candidates` — always *derived*
from traffic-weight/width/degree, never authored), `validation`
(valid/failures/warnings). No robot or algorithm state (CBBA bids,
Karma scores, D* Lite costs, MDPiBT priorities, NH-ORCA velocities,
robot/task state) is ever included — that belongs to a future
simulation/telemetry layer built on top of this schema.

## Tests

`tests/` covers: config validation, geometry primitives, end-to-end
generation validity (no overlaps, in-bounds, irregularity actually
changes geometry), every archetype produces at least one valid layout
across 20 seeds, industry-conditioned generation, graph connectivity
and derived (non-authored) bottlenecks, the validator's reject/tag
behavior, seed+config determinism (byte-identical JSON on rerun), JSON
round-trip (including graph reload) and the no-robot-state guarantee,
and batch diversity reporting. Run with `.venv/bin/pytest -q` (~25-30s).

## Known limitations

- **`rack_orientation=parallel_to_dock`** is preserved as metadata but
  does not currently change the physical grid topology — see
  `generation/storage.py`'s module docstring for why a true axis swap
  was tried and reverted (it orphans zones not at a field corner; fixing
  it properly requires making the zone/dock band packers axis-aware).
- **Dock walls are restricted to north/south** in the sampler for the
  same reason (`generation/zones.py` / `generation/docks.py` only
  support horizontal bands); `l_flow`'s corner logic works within that
  constraint rather than lifting it.
- **`l_flow` and `fishbone`** are simplified/stubbed per the priority
  order in the research spec (Section AF) — see their module docstrings.
- **Fire lanes** are represented as a tag on an existing main aisle
  (an id in `geometry.fire_lanes`), not a separate no-storage polygon.
- **`require_dual_egress_paths` defaults to False** — this version
  models only the picking-aisle graph, not a separate emergency-egress
  corridor system, so single-block/no-interior-cross-aisle layouts are
  structurally tree-shaped and can never satisfy a redundancy
  requirement placed on the same graph. See `ConstraintsConfig`'s
  docstring.
- **Very large batches**: touch-detection is STRtree-accelerated but
  the dual-egress check (when enabled) is capped to a bounded number of
  junctions per layout for tractability on large graphs.

## Exact commands

Generate one layout:
```bash
.venv/bin/python -m fleetnet_layout generate --seed 42 --scale medium --industry ecommerce --archetype grid --visualize
```

Generate 100+ layouts:
```bash
.venv/bin/python -m fleetnet_layout batch --count 100 --seed 42
```
