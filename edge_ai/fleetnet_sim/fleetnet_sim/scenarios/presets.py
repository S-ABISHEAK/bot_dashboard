"""Named fleet+task scenario presets — same pattern as
``warehouse_layout``'s own ``config/presets.py`` (a name -> a bundle of
overrides, still going through the normal config/validation path rather
than hand-authoring a run). These are the *simulation-side* half of a
scenario: fleet size/composition, task arrival, which algorithms run,
and default duration/dt. They compose independently of
``warehouse_layout``'s own layout presets (`--preset` there picks the
warehouse shape; `--preset` here picks what runs on it) — e.g.
`--layout <a bottleneck_heavy-generated layout> --preset bottleneck_stress`
pairs a real chokepoint-heavy warehouse with a fleet/arrival-rate mix
tuned to actually stress it.

Every preset here was tuned from a real, previously-run scenario in this
project's own development (see each docstring for its provenance) rather
than picked arbitrarily.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fleetnet_sim.config.schema import AlgorithmsConfig, FleetConfig, TaskGenConfig


@dataclass(frozen=True)
class ScenarioPreset:
    name: str
    description: str
    fleet: FleetConfig
    tasks: TaskGenConfig
    algorithms: AlgorithmsConfig = field(default_factory=AlgorithmsConfig)
    dt: float = 0.1
    duration_s: float = 300.0


PRESETS: dict[str, ScenarioPreset] = {
    "sparse": ScenarioPreset(
        name="sparse",
        description="Light traffic baseline: few robots, low task arrival, no congestion expected — a control scenario for comparing against denser presets.",
        fleet=FleetConfig(robot_count=6),
        tasks=TaskGenConfig(arrival_rate_per_s=0.3),
        duration_s=300.0,
    ),
    "dense": ScenarioPreset(
        name="dense",
        description="Heavy traffic stress test: many robots, high arrival rate. This is the density range (20-25 robots) where the CBBA announce-livelock bug and rare collisions were actually found in this project's own testing — expect both real conflict and congestion signal, and occasional degraded outcomes (see README's Known Limitations).",
        fleet=FleetConfig(robot_count=25),
        tasks=TaskGenConfig(arrival_rate_per_s=1.5),
        duration_s=300.0,
    ),
    "bottleneck_stress": ScenarioPreset(
        name="bottleneck_stress",
        description="Moderate fleet with aggressive arrival, meant to pair with a warehouse_layout generated with its own 'bottleneck_heavy' preset (real chokepoints), to stress the conflict resolver and congestion detour where the layout is actually narrow, not just where the fleet happens to cluster.",
        fleet=FleetConfig(robot_count=18),
        tasks=TaskGenConfig(arrival_rate_per_s=1.2),
        duration_s=300.0,
    ),
    "eta_corpus": ScenarioPreset(
        name="eta_corpus",
        description="Tuned for the ETA Predictor dataset: moderate density with steady task turnover, so most sampled robot-en-route observations reach a real completion without excessive congestion noise dominating the signal.",
        fleet=FleetConfig(robot_count=12),
        tasks=TaskGenConfig(arrival_rate_per_s=0.6),
        duration_s=300.0,
    ),
    "conflict_corpus": ScenarioPreset(
        name="conflict_corpus",
        description="Tuned for the Conflict Predictor dataset: dense enough that real Karma/MD-PIBT-arbitrated conflicts occur often, without tipping into the CBBA announce-livelock density range covered by the 'dense' preset above.",
        fleet=FleetConfig(robot_count=20),
        tasks=TaskGenConfig(arrival_rate_per_s=1.0),
        duration_s=240.0,
    ),
    "congestion_corpus": ScenarioPreset(
        name="congestion_corpus",
        description="Tuned for the Congestion Predictor dataset — this is the exact fleet/arrival combination used in this project's own 105-run training-data batch, which produced a non-degenerate 64% congestion positive rate on real generated layouts.",
        fleet=FleetConfig(robot_count=15),
        tasks=TaskGenConfig(arrival_rate_per_s=0.8),
        duration_s=180.0,
    ),
}


def get_preset(name: str) -> ScenarioPreset:
    if name not in PRESETS:
        raise KeyError(f"unknown scenario preset {name!r}; available: {sorted(PRESETS)}")
    return PRESETS[name]
