"""Command-line runner for the SwarmShield simulation."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any

from .agents import Agent
from .config import SimulationConfig, load_config
from .world import World


EVENT_FIELDS = (
    "step",
    "event_type",
    "message_id",
    "sender_id",
    "recipient_id",
    "entity_id",
    "details",
    "copy_index",
    "task_id",
    "task_type",
    "deadline",
    "priority",
    "processing_cost",
    "remaining_cost",
    "information_time",
    "resource_id",
)


def run_simulation(
    config: SimulationConfig,
    mode: str,
    policy: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, object]]]:
    """Run the same incremental engine used by the real-time adapter to completion."""
    from .session import SimulationSession

    session = SimulationSession(config, mode, policy)
    while not session.finished:
        session.advance_tick()
    assert session.summary is not None
    return session.summary, session.events


def _event(
    step: int,
    event_type: str,
    message_id: str = "",
    sender_id: str = "",
    recipient_id: str = "",
    entity_id: str = "",
    details: str = "",
    copy_index: int = 0,
    resource_id: str = "",
) -> dict[str, object]:
    return {
        "step": step,
        "event_type": event_type,
        "message_id": message_id,
        "sender_id": sender_id,
        "recipient_id": recipient_id,
        "entity_id": entity_id,
        "details": details,
        "copy_index": copy_index,
        "resource_id": resource_id,
    }


def _simulation_snapshot(
    world: World,
    agents: dict[str, Agent],
    *,
    include_presentation_state: bool = False,
) -> dict[str, object]:
    entities = world.evaluator_snapshot()
    agent_views: list[dict[str, object]] = []
    for agent in agents.values():
        agent_view: dict[str, object] = {"id": agent.agent_id, "x": agent.x, "y": agent.y}
        if include_presentation_state:
            agent_view["heading_rad"] = agent.heading_rad
        if include_presentation_state or agent.vehicle.has_motion_history:
            agent_view.update({
                "uav_status": agent.vehicle.status,
                "speed": agent.vehicle.speed,
                "battery_remaining": agent.vehicle.battery_remaining,
                "distance_travelled": agent.vehicle.distance_travelled,
                "current_task_id": agent.vehicle.current_task_id,
                "recovery_target": list(agent.recovery_target) if agent.recovery_target is not None else None,
                "destination": (
                    list(agent.vehicle.destination)
                    if agent.vehicle.destination is not None else None
                ),
                "final_destination": (
                    list(agent.vehicle.final_destination)
                    if agent.vehicle.final_destination is not None else None
                ),
                "route_waypoints": [list(point) for point in agent.vehicle.route_waypoints],
            })
        agent_views.append(agent_view)
    snapshot = {
        "entities": [
            {"id": entity.entity_id, "x": entity.x, "y": entity.y}
            for entity in entities
        ],
        "protected_zone": {
            "x": world.protected_zone.x,
            "y": world.protected_zone.y,
            "radius": world.protected_zone.radius,
        },
        "agents": agent_views,
        "tracks": [
            {
                "agent_id": agent.agent_id,
                "entity_id": track.entity_id,
                "x": track.x,
                "y": track.y,
                "observed_at": track.observed_at,
            }
            for agent in agents.values()
            for track in agent.tracks.values()
        ],
    }
    if include_presentation_state and not world.geometry.is_empty:
        snapshot["geometry"] = world.geometry.to_dict()
    return snapshot


def write_events(path: str | Path, events: list[dict[str, object]]) -> None:
    event_path = Path(path)
    event_path.parent.mkdir(parents=True, exist_ok=True)
    with event_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=EVENT_FIELDS)
        writer.writeheader()
        writer.writerows(events)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a synthetic SwarmShield scenario")
    parser.add_argument("--config", required=True, help="Path to a JSON scenario configuration")
    parser.add_argument(
        "--mode",
        choices=("independent", "cooperative"),
        default="cooperative",
        help="Whether agents exchange observation reports",
    )
    parser.add_argument(
        "--policy",
        choices=("fixed-priority", "edf"),
        help="Override the scheduler policy selected in the config",
    )
    parser.add_argument("--events", help="Optional path for a CSV event log")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        summary, events = run_simulation(config, args.mode, args.policy)
        if args.events:
            write_events(args.events, events)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
