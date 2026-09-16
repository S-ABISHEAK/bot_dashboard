"""Experiment configuration schema (Section 22).

Every simulation run is driven by one ``ExperimentConfig``. It is stored
verbatim (as JSON) on the ``experiments``/``simulation_runs`` rows so a
run is fully reproducible from seed + config + the referenced layout
file, per Section 4.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CommsBackend(str, Enum):
    INPROCESS = "inprocess"
    ZENOH = "zenoh"


class WarehouseConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    layout_path: str = Field(..., description="Path to a warehouse_layout-generated JSON file.")
    validate_on_load: bool = Field(True, description="Re-check the stored validation.valid flag before simulating.")


class SimulationConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    dt: float = Field(0.1, gt=0, description="Fixed physics/world timestep, seconds.")
    duration_s: float = Field(300.0, gt=0, description="Wall-of-sim-time to run, seconds.")
    seed: int = Field(0, description="Master RNG seed for this run.")
    deterministic: bool = Field(True, description="If True, a single numpy Generator(seed) drives all sampling.")


class FleetConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    robot_count: int = Field(10, ge=1)
    robot_radius_m: float = Field(0.35, gt=0, description="Matches DiffDriveRobot default.")
    max_speed_mps: float = Field(2.0, gt=0)
    max_omega_radps: float = Field(3.0, gt=0)
    max_bundle: int = Field(2, ge=1, description="CBBAAgent.max_bundle.")


class TaskGenConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    arrival_rate_per_s: float = Field(0.5, ge=0, description="Mean new-task arrivals per second (Poisson process).")
    reward: float = Field(100.0, description="Flat CBBA task reward; scoring differentiation comes from priority/distance.")
    max_active_tasks: Optional[int] = Field(None, description="Optional cap on concurrently unassigned tasks (backpressure).")


class AlgorithmsConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    enable_cbba: bool = True
    enable_conflict_resolver: bool = True
    enable_congestion_detour: bool = True
    enable_stall_recovery: bool = True
    enable_unreachable_reassignment: bool = True


class CommunicationConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    backend: CommsBackend = CommsBackend.INPROCESS
    inject_delay_s: float = Field(0.0, ge=0, description="ZenohBus only.")
    inject_loss_rate: float = Field(0.0, ge=0, le=1, description="ZenohBus only.")


class TelemetryConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    robot_state_sample_every_n_ticks: int = Field(5, ge=1, description="Sampling rate for robot_state_ts rows.")
    flush_batch_size: int = Field(500, ge=1)
    flush_interval_s: float = Field(2.0, gt=0)


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    dsn: str = Field("postgresql://fleetnet:fleetnet@localhost:5432/fleetnet_sim")
    echo: bool = False


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_id: str
    run_id: str
    warehouse: WarehouseConfig
    simulation: SimulationConfig
    fleet: FleetConfig
    tasks: TaskGenConfig = TaskGenConfig()
    algorithms: AlgorithmsConfig = AlgorithmsConfig()
    communication: CommunicationConfig = CommunicationConfig()
    telemetry: TelemetryConfig = TelemetryConfig()
    database: DatabaseConfig = DatabaseConfig()
