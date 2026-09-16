"""Wires ``core.engine.Engine``'s event-sink callbacks to the buffered
repository (Section 13). ``robots``/``tasks`` are lifecycle-summary
tables (one row per robot/task, written at run finalization from the
engine's final in-memory state) rather than time series — the
per-instant trail lives in ``robot_state_ts``/``task_lifecycle_events``.
"""
from __future__ import annotations

from dataclasses import dataclass

from fleetnet_sim.storage.repository import BufferedRepository


@dataclass
class TelemetryCollector:
    repo: BufferedRepository
    run_id: str

    def on_robot_sample(self, row: dict) -> None:
        edge = row.pop("current_edge", None) or (None, None)
        task_state = row.pop("task_state", None)
        self.repo.add(
            "robot_state_ts",
            {
                "run_id": self.run_id,
                # The engine's real tick counter — shared across every robot
                # sampled in the same step. Do NOT substitute a self-incrementing
                # row counter here: datasets.conflict_builder groups robot_state_ts
                # rows by (run_id, tick) to reconstruct "who else was where at the
                # same instant," which silently breaks (every group size 1) if
                # this isn't the actual simulation tick.
                "tick": row["tick"],
                "simulation_time": row["simulation_time"],
                "robot_id": row["robot_id"],
                "x": row["x"],
                "y": row["y"],
                "yaw": row["yaw"],
                "current_node_id": row.get("current_node_id"),
                "current_edge_source": edge[0],
                "current_edge_target": edge[1],
                "task_id": row.get("task_id"),
                "task_state": task_state,
                "speed": row["speed"],
                "angular_velocity": row["angular_velocity"],
                "replan_count": row.get("replan_count", 0),
                "distance_travelled": row.get("distance_travelled", 0.0),
            },
        )

    def on_edge_sample(self, ev: dict) -> None:
        self.repo.add(
            "edge_state_ts",
            {
                "run_id": self.run_id,
                "tick": ev["tick"],
                "simulation_time": ev["simulation_time"],
                "edge_source": ev["edge_source"],
                "edge_target": ev["edge_target"],
                "occupancy_count": ev["occupancy_count"],
                "avg_speed": ev["avg_speed"],
                "min_speed": ev["min_speed"],
                "max_speed": ev["max_speed"],
            },
        )

    def on_node_sample(self, ev: dict) -> None:
        self.repo.add(
            "node_state_ts",
            {
                "run_id": self.run_id,
                "tick": ev["tick"],
                "simulation_time": ev["simulation_time"],
                "node_id": ev["node_id"],
                "occupancy_count": ev["occupancy_count"],
            },
        )

    def on_zone_sample(self, ev: dict) -> None:
        self.repo.add(
            "zone_state_ts",
            {
                "run_id": self.run_id,
                "tick": ev["tick"],
                "simulation_time": ev["simulation_time"],
                "zone_type": ev["zone_type"],
                "occupancy_count": ev["occupancy_count"],
                "avg_speed": ev["avg_speed"],
            },
        )

    def on_algorithm_event(self, ev: dict) -> None:
        self.repo.add(
            "algorithm_events",
            {
                "run_id": self.run_id,
                "simulation_time": ev["simulation_time"],
                "robot_id": ev.get("robot_id"),
                "task_id": ev.get("task_id"),
                "algorithm_name": ev["algorithm_name"],
                "trigger": ev["trigger"],
                "input_summary": ev.get("input_summary", {}),
                "output_state": ev.get("output_state", {}),
                "success": ev.get("success", True),
                "execution_time_ms": ev.get("execution_time_ms"),
            },
        )
        out = ev.get("output_state", {})
        if ev["algorithm_name"] == "dstar_lite":
            self.repo.add(
                "route_events",
                {
                    "run_id": self.run_id,
                    "simulation_time": ev["simulation_time"],
                    "robot_id": ev.get("robot_id"),
                    "task_id": ev.get("task_id"),
                    "route_hash": None,
                    "route_length_m": None,
                    "node_expansions": out.get("node_expansions"),
                    "reason": ev.get("trigger", "unknown"),
                },
            )
            if ev.get("trigger") == "congestion_detour":
                self.repo.add(
                    "congestion_events",
                    {
                        "run_id": self.run_id,
                        "tick": ev["tick"],
                        "simulation_time": ev["simulation_time"],
                        "robot_id": ev["robot_id"],
                        "phantom_obstacle_count": out["phantom_obstacle_count"],
                        "detour_path_len": out["detour_path_len"],
                        "original_cost": out["original_cost"],
                        "detour_cost": out["detour_cost"],
                    },
                )
        elif ev["algorithm_name"] == "mdpibt_karma":
            for yielder, winner in out.get("dependency_edges", []):
                self.repo.add(
                    "conflict_events",
                    {
                        "run_id": self.run_id,
                        "tick": ev["tick"],
                        "simulation_time": ev["simulation_time"],
                        "yielder_robot_id": yielder,
                        "winner_robot_id": winner,
                    },
                )

    def on_task_event(self, ev: dict) -> None:
        payload = {k: v for k, v in ev.items() if k not in ("event", "task_id", "simulation_time", "robot_id")}
        self.repo.add(
            "task_lifecycle_events",
            {
                "run_id": self.run_id,
                "simulation_time": ev["simulation_time"],
                "task_id": ev["task_id"],
                "robot_id": ev.get("robot_id"),
                "event": ev["event"],
                "payload": payload,
            },
        )

    def on_comm_event(self, ev: dict) -> None:
        self.repo.add(
            "communication_events",
            {
                "run_id": self.run_id,
                "simulation_time": ev["simulation_time"],
                "message_id": ev["message_id"],
                "topic": ev["topic"],
                "source": ev.get("source"),
                "message_type": ev.get("message_type", "message"),
                "payload_size_bytes": ev.get("payload_size_bytes", -1),
            },
        )

    def finalize(self, engine) -> None:
        for agent in engine.agents.values():
            spawn_x, spawn_y = agent.robot.position()
            self.repo.add(
                "robots",
                {
                    "run_id": self.run_id,
                    "robot_id": agent.robot_id,
                    "robot_type": "AMR",
                    "radius_m": agent.robot.radius,
                    "max_speed_mps": agent.robot.max_speed,
                    "max_omega_radps": agent.robot.max_omega,
                    "spawn_x": spawn_x,
                    "spawn_y": spawn_y,
                    "spawn_time": 0.0,
                },
            )
        for record in engine.task_records.values():
            self.repo.add(
                "tasks",
                {
                    "run_id": self.run_id,
                    "task_id": record.task_id,
                    "task_type": record.task_type,
                    "source_zone_id": record.source_zone_id,
                    "destination_zone_id": record.destination_zone_id,
                    "release_time": record.release_time,
                    "priority": record.priority,
                    "due_time": record.due_time,
                    "assigned_robot_id": record.assigned_robot_id,
                    "assignment_time": record.assignment_time,
                    "planned_distance": record.planned_distance,
                    "actual_distance": record.actual_distance,
                    "start_time": record.start_time,
                    "completion_time": record.completion_time,
                    "waiting_time": record.waiting_time,
                    "replan_count": record.replan_count,
                    "final_status": record.final_status,
                },
            )
        self.repo.flush_all()
