"""SQLAlchemy models for the thin-slice schema (Section 12).

``robot_state_ts``/``algorithm_events``/``route_events`` are TimescaleDB
hypertables. Timescale hypertables partition on a real timestamp column;
since the *authoritative* simulation clock is ``simulation_time``
(float seconds) / ``tick`` (int) — not wall-clock time — every
hypertable also carries ``ingested_at`` (server-side ``now()``), used
only as the partitioning dimension. All real queries filter/order by
``run_id`` + ``simulation_time``/``tick``, never by ``ingested_at``.

``edge_state_ts``/``node_state_ts``/``zone_state_ts`` are the breadth-phase
addition backing the Congestion Predictor dataset (occupancy/speed
aggregated per sample tick over every robot resolved to that edge/node/
zone via ``WorldBridge``).

``conflict_events``/``congestion_events``/``communication_events`` are
promoted, queryable versions of what used to live only inside
``algorithm_events``' JSONB payload. Conflict/congestion promotion is
additive (the raw ``algorithm_events`` audit row is still written too);
communication promotion fully replaces the old JSONB write (see
``CommunicationEvent``'s docstring for why).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Experiment(Base):
    __tablename__ = "experiments"

    experiment_id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    schema_version: Mapped[str] = mapped_column(String)
    sim_version: Mapped[str] = mapped_column(String)
    label_definitions: Mapped[dict] = mapped_column(JSONB, default=dict)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.experiment_id"))
    layout_id: Mapped[str] = mapped_column(String)
    layout_path: Mapped[str] = mapped_column(String)
    seed: Mapped[int] = mapped_column(Integer)
    dt: Mapped[float] = mapped_column(Float)
    config_json: Mapped[dict] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, default="running")  # running | completed | failed
    final_tick: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class Warehouse(Base):
    __tablename__ = "warehouses"

    layout_id: Mapped[str] = mapped_column(String, primary_key=True)
    source_path: Mapped[str] = mapped_column(String)
    archetype: Mapped[str] = mapped_column(String)
    scale_class: Mapped[str] = mapped_column(String)
    industry_type: Mapped[str] = mapped_column(String)
    area_m2: Mapped[float] = mapped_column(Float)
    aspect_ratio: Mapped[float] = mapped_column(Float)
    raw_layout_json: Mapped[dict] = mapped_column(JSONB)


class Robot(Base):
    __tablename__ = "robots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.run_id"))
    robot_id: Mapped[str] = mapped_column(String)
    robot_type: Mapped[str] = mapped_column(String, default="AMR")
    radius_m: Mapped[float] = mapped_column(Float)
    max_speed_mps: Mapped[float] = mapped_column(Float)
    max_omega_radps: Mapped[float] = mapped_column(Float)
    spawn_x: Mapped[float] = mapped_column(Float)
    spawn_y: Mapped[float] = mapped_column(Float)
    spawn_time: Mapped[float] = mapped_column(Float, default=0.0)


class TaskRow(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.run_id"))
    task_id: Mapped[str] = mapped_column(String)
    task_type: Mapped[str] = mapped_column(String)
    source_zone_id: Mapped[str] = mapped_column(String)
    destination_zone_id: Mapped[str] = mapped_column(String)
    release_time: Mapped[float] = mapped_column(Float)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    due_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    assigned_robot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    assignment_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    planned_distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_distance: Mapped[float] = mapped_column(Float, default=0.0)
    start_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    completion_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    waiting_time: Mapped[float] = mapped_column(Float, default=0.0)
    replan_count: Mapped[int] = mapped_column(Integer, default=0)
    final_status: Mapped[str] = mapped_column(String, default="pending")


class RobotStateTS(Base):
    """Hypertable, partitioned on ``ingested_at`` (see module docstring)."""

    __tablename__ = "robot_state_ts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, default=_utcnow)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.run_id"))
    tick: Mapped[int] = mapped_column(BigInteger)
    simulation_time: Mapped[float] = mapped_column(Float)
    robot_id: Mapped[str] = mapped_column(String)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    yaw: Mapped[float] = mapped_column(Float)
    current_node_id: Mapped[str | None] = mapped_column(String, nullable=True)
    current_edge_source: Mapped[str | None] = mapped_column(String, nullable=True)
    current_edge_target: Mapped[str | None] = mapped_column(String, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    task_state: Mapped[str | None] = mapped_column(String, nullable=True)
    speed: Mapped[float] = mapped_column(Float)
    angular_velocity: Mapped[float] = mapped_column(Float)
    replan_count: Mapped[int] = mapped_column(Integer, default=0)
    distance_travelled: Mapped[float] = mapped_column(Float, default=0.0)


class AlgorithmEvent(Base):
    """Hypertable. Captures every meaningful CBBA/D* Lite/Karma+MDPiBT
    call site (Section 8). Congestion/conflict/communication events are
    logged here with ``trigger`` set accordingly until they're promoted
    to dedicated tables (see module docstring)."""

    __tablename__ = "algorithm_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, default=_utcnow)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.run_id"))
    simulation_time: Mapped[float] = mapped_column(Float)
    robot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    algorithm_name: Mapped[str] = mapped_column(String)
    algorithm_version: Mapped[str] = mapped_column(String, default="fleet_sih_core")
    trigger: Mapped[str] = mapped_column(String)
    input_summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    output_state: Mapped[dict] = mapped_column(JSONB, default=dict)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    execution_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)


class RouteEvent(Base):
    """Hypertable. One row per ``route_planned``/``route_replanned``."""

    __tablename__ = "route_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, default=_utcnow)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.run_id"))
    simulation_time: Mapped[float] = mapped_column(Float)
    robot_id: Mapped[str] = mapped_column(String)
    task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    route_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    route_length_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    node_expansions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(String)


class EdgeStateTS(Base):
    """Hypertable. One row per (run_id, edge, sampled tick) — occupancy/
    speed aggregated across every robot whose ``nearest_edge`` resolved
    to this (source, target) at that sample. This is the Congestion
    Predictor's dependency (see plan's Known Limitations — now built)."""

    __tablename__ = "edge_state_ts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, default=_utcnow)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.run_id"))
    tick: Mapped[int] = mapped_column(BigInteger)
    simulation_time: Mapped[float] = mapped_column(Float)
    edge_source: Mapped[str] = mapped_column(String)
    edge_target: Mapped[str] = mapped_column(String)
    occupancy_count: Mapped[int] = mapped_column(Integer)
    avg_speed: Mapped[float] = mapped_column(Float)
    min_speed: Mapped[float] = mapped_column(Float)
    max_speed: Mapped[float] = mapped_column(Float)


class NodeStateTS(Base):
    """Hypertable. One row per (run_id, node, sampled tick)."""

    __tablename__ = "node_state_ts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, default=_utcnow)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.run_id"))
    tick: Mapped[int] = mapped_column(BigInteger)
    simulation_time: Mapped[float] = mapped_column(Float)
    node_id: Mapped[str] = mapped_column(String)
    occupancy_count: Mapped[int] = mapped_column(Integer)


class ZoneStateTS(Base):
    """Hypertable. One row per (run_id, zone_type, sampled tick)."""

    __tablename__ = "zone_state_ts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, default=_utcnow)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.run_id"))
    tick: Mapped[int] = mapped_column(BigInteger)
    simulation_time: Mapped[float] = mapped_column(Float)
    zone_type: Mapped[str] = mapped_column(String)
    occupancy_count: Mapped[int] = mapped_column(Integer)
    avg_speed: Mapped[float] = mapped_column(Float)


class ConflictEvent(Base):
    """Hypertable. Promoted out of ``algorithm_events``' JSONB (see that
    model's docstring) — one row per ``(yielder, winner)`` pair actively
    in conflict at a tick, i.e. one row per element of
    ``ConflictResolver.dependency_edges``, the same real pairwise ground
    truth ``datasets/conflict_builder.py`` and ``replay/loader.py`` use.
    The raw ``algorithm_events`` row (with ``should_yield``/positions
    context) is still written too — this is a queryable index into it,
    not a replacement."""

    __tablename__ = "conflict_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, default=_utcnow)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.run_id"))
    tick: Mapped[int] = mapped_column(BigInteger)
    simulation_time: Mapped[float] = mapped_column(Float)
    yielder_robot_id: Mapped[str] = mapped_column(String)
    winner_robot_id: Mapped[str] = mapped_column(String)


class CongestionEvent(Base):
    """Hypertable. Promoted out of ``algorithm_events``' JSONB — one row
    per congestion-detour attempt that actually committed
    (``core/engine.py::_attempt_congestion_detour``). Distinct from
    ``edge_state_ts`` (continuous occupancy) — this is the discrete
    "a detour was triggered" event."""

    __tablename__ = "congestion_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, default=_utcnow)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.run_id"))
    tick: Mapped[int] = mapped_column(BigInteger)
    simulation_time: Mapped[float] = mapped_column(Float)
    robot_id: Mapped[str] = mapped_column(String)
    phantom_obstacle_count: Mapped[int] = mapped_column(Integer)
    detour_path_len: Mapped[int] = mapped_column(Integer)
    original_cost: Mapped[float] = mapped_column(Float)
    detour_cost: Mapped[float] = mapped_column(Float)


class CommunicationEvent(Base):
    """Hypertable. Promoted out of ``algorithm_events``' JSONB — one row
    per ``MessageBus.publish`` call (``integration/comms_adapter.py``'s
    ``LoggingBus``). Unlike conflict/congestion events, this one fully
    replaces the old ``algorithm_events`` write (it fired on every single
    publish — CBBA's bid cascades make this the highest-volume event type
    by far, and nothing read it out of ``algorithm_events`` for datasets,
    so folding it into the generic JSONB table was pure bloat)."""

    __tablename__ = "communication_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, default=_utcnow)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.run_id"))
    simulation_time: Mapped[float] = mapped_column(Float)
    message_id: Mapped[str] = mapped_column(String)
    topic: Mapped[str] = mapped_column(String)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    message_type: Mapped[str] = mapped_column(String)
    payload_size_bytes: Mapped[int] = mapped_column(Integer)


class TaskLifecycleEvent(Base):
    __tablename__ = "task_lifecycle_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.run_id"))
    simulation_time: Mapped[float] = mapped_column(Float)
    task_id: Mapped[str] = mapped_column(String)
    robot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    event: Mapped[str] = mapped_column(String)  # task_created | task_assigned | task_started | task_completed | task_failed
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)


class RunMetrics(Base):
    __tablename__ = "run_metrics"

    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.run_id"), primary_key=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    metrics_json: Mapped[dict] = mapped_column(JSONB)


class ModelDatasetRegistry(Base):
    __tablename__ = "model_dataset_registry"

    dataset_id: Mapped[str] = mapped_column(String, primary_key=True)
    model_name: Mapped[str] = mapped_column(String)  # congestion | conflict | eta
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    feature_version: Mapped[str] = mapped_column(String)
    label_definition: Mapped[dict] = mapped_column(JSONB)
    horizon_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_run_ids: Mapped[list] = mapped_column(JSONB)
    output_path: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="ready")  # ready | not_ready


class TrainedModelRegistry(Base):
    """One row per baseline model trained by ``fleetnet_sim/models/`` —
    keeps trained models traceable back to the exact dataset (and hence
    the exact run_ids/telemetry) that produced them, same philosophy as
    ``model_dataset_registry`` for datasets."""

    __tablename__ = "trained_model_registry"

    model_id: Mapped[str] = mapped_column(String, primary_key=True)
    model_name: Mapped[str] = mapped_column(String)  # congestion | conflict | eta
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    dataset_id: Mapped[str | None] = mapped_column(String, nullable=True)
    dataset_path: Mapped[str] = mapped_column(String)
    algorithm: Mapped[str] = mapped_column(String)  # e.g. "GradientBoostingRegressor"
    feature_columns: Mapped[list] = mapped_column(JSONB)
    metrics_json: Mapped[dict] = mapped_column(JSONB)
    model_path: Mapped[str] = mapped_column(String)
