"""Versioned newline-delimited JSON protocol for the Godot presentation layer."""

from __future__ import annotations

import copy
import json
import sys
from typing import Any

from .comparisons import list_saved_comparisons, load_saved_comparison, run_matched_comparison
from .missions import evaluate_mission, load_mission, mission_ids, save_run_artifacts
from .tasks import parse_task_definitions
from .session import SimulationSession


PROTOCOL_VERSION = 1
MAX_ADVANCE_TICKS = 500
SUPPORTED_SPEEDS = {0.25, 0.5, 1.0, 2.0, 4.0}


class ProtocolServer:
    def __init__(self) -> None:
        self.session: SimulationSession | None = None
        self.scenario_id: str | None = None
        self.mission: dict[str, Any] | None = None
        self.mode = "cooperative"
        self.policy: str | None = None
        self.seed: int | None = None
        self.paused = False
        self.speed = 1.0
        self.artifact_path: str | None = None
        self.stopping = False

    def handle_line(self, line: str) -> dict[str, Any]:
        request_id: Any = None
        try:
            try:
                request = json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            except (json.JSONDecodeError, ValueError) as error:
                raise ProtocolError("malformed_json", "request line is not valid JSON") from error
            if not isinstance(request, dict):
                raise ProtocolError("invalid_request", "request must be a JSON object")
            request_id = request.get("request_id")
            if request_id is not None and (not isinstance(request_id, (str, int)) or isinstance(request_id, bool)):
                raise ProtocolError("invalid_request_id", "request_id must be a string, integer, or null")
            version = request.get("version")
            if type(version) is not int or version != PROTOCOL_VERSION:
                code = "protocol_version_required" if version is None else "unsupported_protocol_version"
                raise ProtocolError(code, f"protocol version {PROTOCOL_VERSION} is required")
            command = request.get("command")
            if not isinstance(command, str):
                raise ProtocolError("invalid_command", "command must be a string")
            result = self._dispatch(command, request.get("payload", {}))
            return {"version": PROTOCOL_VERSION, "request_id": request_id, "ok": True, "result": result}
        except ProtocolError as error:
            return {
                "version": PROTOCOL_VERSION,
                "request_id": request_id,
                "ok": False,
                "error": {"code": error.code, "message": str(error)},
            }
        except (TypeError, ValueError, OSError, RuntimeError, KeyError) as error:
            return {
                "version": PROTOCOL_VERSION,
                "request_id": request_id,
                "ok": False,
                "error": {"code": "command_failed", "message": str(error)},
            }
        except Exception as error:  # keep protocol stdout valid if the backend raises unexpectedly
            print(f"protocol internal error: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
            return {
                "version": PROTOCOL_VERSION,
                "request_id": request_id,
                "ok": False,
                "error": {"code": "internal_error", "message": "simulation command failed"},
            }

    def _dispatch(self, command: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProtocolError("invalid_payload", "payload must be a JSON object")
        if command == "list_scenarios":
            return {"scenarios": mission_ids()}
        if command == "list_saved_comparisons":
            return {"comparisons": list_saved_comparisons()}
        if command == "load_saved_comparison":
            comparison_id = payload.get("comparison_id")
            if not isinstance(comparison_id, str):
                raise ProtocolError("invalid_comparison", "comparison_id must be a string")
            comparison = load_saved_comparison(comparison_id)
            if comparison is None:
                raise ProtocolError("unknown_comparison", "saved comparison was not found")
            return {"comparison": comparison}
        if command == "run_matched_comparison":
            if self.session is not None and not self.session.finished:
                raise ProtocolError("run_active", "finish or reset the live mission before starting a matched comparison")
            scenario = payload.get("scenario")
            dimension = payload.get("dimension", "scheduler")
            start_seed = payload.get("start_seed", 42)
            seed_count = payload.get("seed_count", 5)
            mode = payload.get("mode", "cooperative")
            policy = payload.get("policy", "fixed-priority")
            if not isinstance(scenario, str):
                raise ProtocolError("invalid_comparison", "scenario must be a mission identifier")
            if not isinstance(dimension, str):
                raise ProtocolError("invalid_comparison", "dimension must be 'scheduler' or 'sharing'")
            if not isinstance(start_seed, int) or isinstance(start_seed, bool) or start_seed < 0:
                raise ProtocolError("invalid_comparison", "start_seed must be a non-negative integer")
            if not isinstance(seed_count, int) or isinstance(seed_count, bool) or not 2 <= seed_count <= 30:
                raise ProtocolError("invalid_comparison", "seed_count must be from 2 to 30")
            if not isinstance(mode, str) or mode not in ("independent", "cooperative"):
                raise ProtocolError("invalid_comparison", "mode must be 'independent' or 'cooperative'")
            if not isinstance(policy, str) or policy not in ("fixed-priority", "edf"):
                raise ProtocolError("invalid_comparison", "policy must be 'fixed-priority' or 'edf'")
            try:
                return run_matched_comparison(scenario, start_seed, seed_count, dimension, mode, policy)
            except ValueError as error:
                raise ProtocolError("invalid_comparison", str(error)) from error
        if command == "start_run":
            if self.session is not None and not self.session.finished:
                raise ProtocolError("run_active", "finish or reset the current run before starting another")
            scenario = payload.get("scenario")
            seed = payload.get("seed")
            if not isinstance(scenario, str):
                raise ProtocolError("invalid_scenario", "scenario must be a mission identifier")
            if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool) or seed < 0):
                raise ProtocolError("invalid_seed", "seed must be a non-negative integer")
            mode = payload.get("mode", "cooperative")
            policy = payload.get("policy")
            if not isinstance(mode, str) or mode not in ("independent", "cooperative"):
                raise ProtocolError("invalid_mode", "mode must be independent or cooperative")
            if policy is not None and (not isinstance(policy, str) or policy not in ("fixed-priority", "edf")):
                raise ProtocolError("invalid_policy", "policy must be fixed-priority or edf")
            try:
                config, mission = load_mission(scenario, seed)
            except ValueError as error:
                raise ProtocolError("invalid_scenario", str(error)) from error
            task_definitions = parse_task_definitions(
                mission.get("tasks", []), config.world_width, config.world_height, config.steps,
            )
            self.session = SimulationSession(
                config, mode, policy, mission_tasks=task_definitions,
                mission_id=scenario, enable_presentation_coverage=True,
            )
            self.session.assign_pending_mission_tasks()
            self.session.run_autonomous_behaviors()
            self.scenario_id, self.mission = scenario, mission
            self.mode, self.policy, self.seed = mode, policy, config.seed
            self.paused, self.speed, self.artifact_path = False, 1.0, None
            return {"scenario": scenario, "name": mission["name"], "seed": config.seed, "tick": 0, "status": "running"}
        if command == "pause_run":
            self._require_active()
            if self.session.finished:
                raise ProtocolError("run_completed", "completed runs cannot be paused")
            self.paused = True
            return {"status": "paused", "tick": self.session.current_step}
        if command == "resume_run":
            self._require_active()
            if self.session.finished:
                raise ProtocolError("run_completed", "completed runs cannot be resumed")
            self.paused = False
            return {"status": "running", "tick": self.session.current_step}
        if command == "reset_run":
            if self.scenario_id is None:
                raise ProtocolError("no_run", "there is no run to reset")
            config, mission = load_mission(self.scenario_id, self.seed)
            task_definitions = parse_task_definitions(
                mission.get("tasks", []), config.world_width, config.world_height, config.steps,
            )
            self.session = SimulationSession(
                config, self.mode, self.policy, mission_tasks=task_definitions,
                mission_id=self.scenario_id, enable_presentation_coverage=True,
            )
            self.session.assign_pending_mission_tasks()
            self.session.run_autonomous_behaviors()
            self.mission = mission
            self.paused = False
            self.artifact_path = None
            return {"status": "running", "tick": 0, "scenario": self.scenario_id, "seed": config.seed}
        if command == "set_simulation_speed":
            speed = payload.get("speed")
            if not isinstance(speed, (int, float)) or isinstance(speed, bool) or float(speed) not in SUPPORTED_SPEEDS:
                raise ProtocolError("invalid_speed", "speed must be one of 0.25, 0.5, 1, 2, or 4")
            self.speed = float(speed)
            return {"speed": self.speed, "tick": self.session.current_step if self.session else 0}
        if command == "advance_ticks":
            self._require_active()
            if self.session.finished:
                raise ProtocolError("run_completed", "run has reached its configured horizon")
            if self.paused:
                raise ProtocolError("run_paused", "resume the run before advancing simulation ticks")
            count = payload.get("count", 1)
            if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= MAX_ADVANCE_TICKS:
                raise ProtocolError("invalid_tick_count", f"count must be an integer from 1 to {MAX_ADVANCE_TICKS}")
            snapshots = []
            for _ in range(count):
                if self.session.finished:
                    break
                snapshots.append(self.session.advance_tick())
            self._save_completed_run()
            return {
                "advanced": len(snapshots),
                "tick": self.session.current_step,
                "status": "completed" if self.session.finished else "running",
                "snapshot": self._snapshot(),
                "events": self.session.sorted_events()[-120:],
                "summary": self.session.summary,
                "artifact_path": self.artifact_path,
            }
        if command == "get_snapshot":
            self._require_active()
            return self._snapshot()
        if command == "inspect_agent":
            self._require_active()
            agent_id = payload.get("agent_id")
            if not isinstance(agent_id, str):
                raise ProtocolError("invalid_agent", "agent_id must be a string")
            detail = self.session.inspect_agent(agent_id)
            if detail is None:
                raise ProtocolError("unknown_agent", f"unknown agent '{agent_id}'")
            return detail
        if command == "apply_intervention":
            self._require_active()
            if self.session.finished:
                raise ProtocolError("run_completed", "interventions cannot change a finalized run")
            action = payload.get("action")
            parameters = payload.get("parameters", {})
            if not isinstance(action, str) or not isinstance(parameters, dict):
                raise ProtocolError("invalid_intervention", "action must be a string and parameters an object")
            result = self.session.apply_intervention(action, parameters)
            return result
        if command == "end_run":
            self._require_active()
            self.session.finalize()
            self._save_completed_run()
            return {"status": "completed" if self.session.current_step >= self.session.config.steps else "incomplete", "tick": self.session.current_step, "summary": self.session.summary, "artifact_path": self.artifact_path}
        if command == "shutdown":
            if self.session is not None and not self.session.finished:
                self.session.finalize()
                self._save_completed_run()
            self.stopping = True
            return {"status": "shutdown", "artifact_path": self.artifact_path}
        raise ProtocolError("unknown_command", f"unsupported command '{command}'")

    def _require_active(self) -> None:
        if self.session is None:
            raise ProtocolError("no_run", "start a scenario before using this command")

    def _snapshot(self) -> dict[str, Any]:
        assert self.session is not None
        snapshot = self.session.snapshot()
        snapshot["pending_message_links"] = self.session.pending_message_details()
        if self.mission is not None:
            for track in snapshot.get("world", {}).get("tracks", []):
                agent = self.session.agents.get(str(track.get("agent_id", "")))
                source = agent.tracks.get(str(track.get("entity_id", ""))) if agent else None
                if source is not None:
                    track["source_agent_id"] = source.source_agent_id
                    track["confidence"] = source.confidence
            mission_for_evaluation = self._mission_for_evaluation()
            evaluation = evaluate_mission(
                mission_for_evaluation,
                snapshot["metrics"],
                completed=self.session.current_step >= self.session.config.steps,
            )
            snapshot["mission"] = {
                "id": self.mission.get("id"),
                "name": self.mission.get("name"),
                "description": self.mission.get("description", ""),
                "prototype": bool(self.mission.get("prototype", False)),
                "status": "running" if not self.session.finished else evaluation["status"],
                "team_mode": self.session.mode,
                "scheduler_policy": self.session.policy,
                "objectives": evaluation["objectives"],
                "scoring_weights": self.mission.get("scoring_weights", {}),
                "tasks": snapshot.get("mission_tasks", []),
                "protection_zones": snapshot.get("world", {}).get("protection_zones", []),
            }
        if self.paused and not self.session.finished:
            snapshot["status"] = "paused"
            if "mission" in snapshot:
                snapshot["mission"]["status"] = "paused"
        return snapshot

    def finalize_on_exit(self) -> None:
        if self.session is not None and not self.session.finished:
            self.session.finalize()
            self._save_completed_run()

    def _mission_for_evaluation(self) -> dict[str, Any]:
        assert self.mission is not None
        mission = copy.deepcopy(self.mission)
        if self.session is None or not self.session.protection_task_ids:
            return mission
        if not any(
            objective.get("metric") == "entity_protection_task_completion_rate"
            for objective in mission.get("objectives", []) if isinstance(objective, dict)
        ):
            mission.setdefault("objectives", []).append({
                "id": "entity_protection_monitoring",
                "label": "Complete all designated entity monitoring tasks",
                "metric": "entity_protection_task_completion_rate",
                "operator": ">=",
                "target": 1.0,
            })
        existing_ids = {str(task.get("task_id", "")) for task in mission.get("tasks", []) if isinstance(task, dict)}
        for task_id in self.session.protection_task_ids:
            task = self.session.mission_tasks.get(task_id)
            if task is not None and task_id not in existing_ids:
                mission.setdefault("tasks", []).append(task.definition.to_dict())
                existing_ids.add(task_id)
        return mission

    def _save_completed_run(self) -> None:
        if self.session is None or not self.session.finished or self.mission is None or self.artifact_path:
            return
        path = save_run_artifacts(self.session, self._mission_for_evaluation())
        self.artifact_path = str(path.resolve())


class ProtocolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def main() -> int:
    server = ProtocolServer()
    for line in sys.stdin:
        response = server.handle_line(line)
        try:
            sys.stdout.write(json.dumps(response, separators=(",", ":"), allow_nan=False) + "\n")
            sys.stdout.flush()
        except (BrokenPipeError, OSError):
            server.finalize_on_exit()
            return 0
        if server.stopping:
            break
    server.finalize_on_exit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
