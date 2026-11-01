import csv
import io
import json
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from swarmshield.config import SimulationConfig, load_config
from swarmshield.missions import calculate_score, evaluate_mission, load_mission
from swarmshield.network import Envelope
from swarmshield.observations import Observation
from swarmshield.protocol import PROTOCOL_VERSION, ProtocolServer
from swarmshield.runner import EVENT_FIELDS, run_simulation
from swarmshield.session import SimulationSession
from swarmshield.tasks import parse_task_definitions


ROOT = Path(__file__).resolve().parents[1]


def request(server, command, payload=None, version=PROTOCOL_VERSION, request_id="test"):
    return server.handle_line(json.dumps({
        "version": version,
        "request_id": request_id,
        "command": command,
        "payload": payload or {},
    }))


class RealtimeSessionTests(unittest.TestCase):
    def setUp(self):
        self.config = SimulationConfig(
            seed=17,
            steps=8,
            world_width=20,
            world_height=20,
            observer_count=2,
            entity_count=3,
            detection_range=100,
            detection_probability=1.0,
            position_noise_std=0.0,
            max_track_age_steps=8,
            delivery_probability=1.0,
            max_latency_steps=0,
            duplicate_probability=0.0,
            processing_capacity_per_step=1000,
            min_task_deadline_steps=0,
            max_task_deadline_steps=0,
            max_task_processing_cost=1,
            coordination_task_duration_steps=1,
        )

    def test_fixed_ticks_match_headless_full_run(self):
        session = SimulationSession(self.config, "cooperative", "edf")
        first = session.advance_tick()
        self.assertEqual(session.current_step, 1)
        self.assertEqual(len(first["entities"]), self.config.entity_count)
        while not session.finished:
            session.advance_tick()
        expected_summary, expected_events = run_simulation(self.config, "cooperative", "edf")
        actual_summary = dict(session.summary)
        actual_summary["metrics"] = dict(actual_summary["metrics"])
        actual_summary["metrics"].pop("wall_clock_runtime_seconds")
        expected_summary["metrics"].pop("wall_clock_runtime_seconds")
        self.assertEqual(actual_summary, expected_summary)
        self.assertEqual(session.events, expected_events)

    def test_each_advance_is_one_reproducible_logical_tick(self):
        sessions = [
            SimulationSession(self.config, "cooperative", "edf"),
            SimulationSession(self.config, "cooperative", "edf"),
        ]
        trajectories = [[], []]
        for expected_tick in range(1, 4):
            for index, session in enumerate(sessions):
                snapshot = session.advance_tick()
                self.assertEqual(session.current_step, expected_tick)
                trajectories[index].append(snapshot)
        self.assertEqual(trajectories[0], trajectories[1])
        self.assertEqual(
            [event["step"] for event in sessions[0].trace_events],
            [1, 2, 3],
        )

    def test_sensor_coverage_is_local_then_shared_only_after_report_application(self):
        config = replace(
            self.config,
            detection_range=6.0,
            position_noise_std=0.0,
            entity_count=2,
            min_task_deadline_steps=5,
            max_task_deadline_steps=5,
        )
        session = SimulationSession(config, "cooperative", "edf", enable_presentation_coverage=True)
        session.agents["agent-001"].vehicle.x = 2.0
        session.agents["agent-001"].vehicle.y = 2.0
        session.agents["agent-002"].vehicle.x = 18.0
        session.agents["agent-002"].vehicle.y = 18.0
        for entity, position in zip(session.world._entities, ((4.0, 2.0), (18.0, 16.0))):
            entity.x, entity.y = position
            entity.vx = entity.vy = 0.0
        session.advance_tick()
        self.assertTrue(session.local_sensor_coverage["agent-001"])
        self.assertTrue(session.local_sensor_coverage["agent-002"])
        self.assertFalse(session.shared_sensor_coverage["agent-002"])

        session.advance_tick()
        self.assertTrue(session.shared_sensor_coverage["agent-002"])
        snapshot = session.snapshot()["world"]
        self.assertEqual(snapshot["sensor_coverage_cell_size"], 2.5)
        self.assertTrue(snapshot["sensor_coverage_cells"])
        received_shared_area = any(
            cell["agent_id"] == "agent-002" and cell["shared_observed_at"] is not None
            for cell in snapshot["sensor_coverage_cells"]
        )
        self.assertTrue(received_shared_area)

    def test_sensor_coverage_respects_heading_fov_and_range(self):
        config = replace(
            self.config,
            detection_range=6.0,
            field_of_view_degrees=90.0,
            detection_probability=1.0,
        )
        session = SimulationSession(config, "independent", "edf", enable_presentation_coverage=True)
        agent = session.agents["agent-001"]
        visible = set(session._sensor_coverage_for_pose(agent, (1, 10.0, 10.0, 0.0)))
        self.assertIn((5, 4), visible)  # cell center is forward and in range
        self.assertNotIn((2, 4), visible)  # behind the sensor heading
        self.assertNotIn((7, 4), visible)  # beyond the sensor radius

    def test_live_metrics_expose_queue_pressure_deadline_urgency_and_pending_routes(self):
        config = replace(
            self.config,
            seed=19,
            max_latency_steps=5,
            processing_capacity_per_step=1,
            queue_capacity=20,
            min_task_deadline_steps=1,
            max_task_deadline_steps=8,
        )
        session = SimulationSession(config, "cooperative", "fixed-priority")
        session.advance_tick()
        metrics = session.live_metrics()
        pending = session.pending_message_details()

        self.assertGreater(metrics["queue_backlog_tasks"], 0)
        self.assertEqual(metrics["queue_capacity"], 20)
        self.assertGreater(metrics["urgent_deadline_tasks"], 0)
        self.assertIsNotNone(metrics["next_deadline_slack_steps"])
        self.assertTrue(pending)
        self.assertTrue(all(message["sender_id"] != message["recipient_id"] for message in pending))
        self.assertTrue(all(message["delivery_step"] > message["sent_step"] for message in pending))
        self.assertTrue(all(message["protocol_version"] == 1 for message in pending))
        self.assertTrue(all(message["message_type"] == "observation" for message in pending))
        self.assertTrue(all(message["valid_until_step"] is None for message in pending))

    def test_session_rejects_unsupported_message_version_and_type(self):
        session = SimulationSession(self.config, "independent")
        observation = Observation("entity-1", 1.0, 2.0, 1, "agent-001")
        future_version = Envelope(
            "future-version", "agent-001", "agent-002", observation, 1, 1,
            protocol_version=2,
        )
        unsupported_type = Envelope(
            "future-type", "agent-001", "agent-002", observation, 1, 1,
            message_type="task",
        )

        self.assertEqual(session._receive_message(future_version), "unsupported_message_version")
        self.assertEqual(session._receive_message(unsupported_type), "unsupported_message_type")
        self.assertEqual(session.agents["agent-002"].tracks, {})

    def test_presentation_feed_records_only_successful_local_and_shared_track_updates(self):
        config = replace(self.config, detection_range=0.0)
        session = SimulationSession(config, "independent")
        source = session.agents["agent-001"]
        recipient = session.agents["agent-002"]

        local = Observation("entity-local", 2.0, 3.0, 0, source.agent_id)
        shared = Observation("entity-shared", 5.0, 6.0, 0, source.agent_id)
        stale = Observation("entity-shared", 1.0, 1.0, -1, source.agent_id)
        self.assertEqual(session._apply_report(source, local), "updated")
        self.assertEqual(session._apply_report(recipient, shared), "updated")
        self.assertEqual(session._apply_report(recipient, stale), "stale")

        updates = session.presentation_events
        self.assertEqual([event["event_type"] for event in updates], ["track_updated", "track_updated"])
        self.assertEqual(updates[0]["sender_id"], source.agent_id)
        self.assertEqual(updates[0]["recipient_id"], source.agent_id)
        self.assertEqual(json.loads(str(updates[0]["details"]))["provenance"], "local")
        self.assertEqual(updates[1]["sender_id"], source.agent_id)
        self.assertEqual(updates[1]["recipient_id"], recipient.agent_id)
        self.assertEqual(json.loads(str(updates[1]["details"]))["provenance"], "shared")
        self.assertEqual(session.snapshot()["presentation_events"], updates)
        self.assertNotIn("track_updated", [event["event_type"] for event in session.sorted_events()])

    def test_distinct_local_discoveries_share_only_after_network_delivery_and_application(self):
        class FixedNetworkRng:
            @staticmethod
            def random():
                return 0.0

            @staticmethod
            def randint(low, high):
                return high

        config = replace(
            self.config,
            steps=8,
            world_width=20,
            world_height=10,
            observer_count=2,
            entity_count=2,
            detection_range=2.0,
            detection_probability=1.0,
            position_noise_std=0.0,
            max_latency_steps=2,
            duplicate_probability=0.0,
            processing_capacity_per_step=1000,
            min_task_deadline_steps=8,
            max_task_deadline_steps=8,
            max_task_processing_cost=1,
            partition_enabled=False,
        )

        def make_session(delivery_probability):
            session = SimulationSession(
                replace(config, delivery_probability=delivery_probability),
                "cooperative",
                "edf",
            )
            session.network._rng = FixedNetworkRng()
            session.agents["agent-001"].vehicle.x = 18.0
            session.agents["agent-001"].vehicle.y = 5.0
            session.agents["agent-002"].vehicle.x = 2.0
            session.agents["agent-002"].vehicle.y = 5.0
            for entity, x in zip(session.world._entities, (2.0, 18.0)):
                entity.x, entity.y, entity.vx, entity.vy = x, 5.0, 0.0, 0.0
            return session

        cooperative = make_session(1.0)
        cooperative.advance_tick()
        left = cooperative.agents["agent-002"]
        right = cooperative.agents["agent-001"]
        self.assertEqual(set(left.tracks), {"entity-001"})
        self.assertEqual(set(right.tracks), {"entity-002"})
        self.assertEqual(cooperative.network.pending_messages, 2)
        self.assertFalse(any(
            event["event_type"] == "track_updated" and event["sender_id"] != event["recipient_id"]
            for event in cooperative.presentation_events
        ))
        cooperative.advance_tick()
        self.assertEqual(set(left.tracks), {"entity-001"})
        self.assertEqual(set(right.tracks), {"entity-002"})
        cooperative.advance_tick()
        self.assertEqual(set(left.tracks), {"entity-001", "entity-002"})
        self.assertEqual(set(right.tracks), {"entity-001", "entity-002"})
        self.assertTrue(any(
            event["event_type"] == "message_delivered" and event["details"] == "queued"
            for event in cooperative.network.events
        ))
        self.assertTrue(any(
            event["event_type"] == "track_updated"
            and json.loads(str(event["details"]))["provenance"] == "shared"
            for event in cooperative.presentation_events
        ))

        lossy = make_session(0.0)
        for _ in range(4):
            lossy.advance_tick()
        self.assertEqual(set(lossy.agents["agent-002"].tracks), {"entity-001"})
        self.assertEqual(set(lossy.agents["agent-001"].tracks), {"entity-002"})
        self.assertGreater(lossy.network.dropped_originals, 0)

    def test_session_network_uses_current_uav_positions_for_range(self):
        config = replace(self.config, communication_range=5.0)
        session = SimulationSession(config, "cooperative")
        sender = session.agents["agent-001"]
        recipient = session.agents["agent-002"]
        sender.vehicle.x, sender.vehicle.y = 1.0, 1.0
        recipient.vehicle.x, recipient.vehicle.y = 10.0, 1.0
        observation = Observation("entity-1", 2.0, 1.0, 0, sender.agent_id)

        session._apply_local_report(sender, observation, (recipient.agent_id,))

        self.assertEqual(session.network.sent_originals, 1)
        self.assertEqual(session.network.dropped_originals, 1)
        self.assertEqual(session.network.pending_messages, 0)
        self.assertEqual(session.network.events[-1]["details"], "out_of_range")
        metrics = session.live_metrics()
        self.assertEqual(metrics["communication_range"], 5.0)
        self.assertEqual(metrics["message_retry_attempts"], 0)

    def test_intervention_sequence_is_reproducible_and_validated(self):
        results = []
        for _ in range(2):
            session = SimulationSession(self.config, "cooperative", "fixed-priority")
            session.advance_tick()
            accepted = session.apply_intervention("set_scheduler_policy", {"policy": "edf"})
            rejected = session.apply_intervention("set_scheduler_policy", {"policy": "random"})
            self.assertTrue(accepted["accepted"])
            self.assertFalse(rejected["accepted"])
            while not session.finished:
                session.advance_tick()
            results.append((session.events, session.interventions, session.scheduler.policy))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][2], "edf")

    def test_player_destination_intervention_is_validated_recorded_and_reproducible(self):
        results = []
        for _ in range(2):
            session = SimulationSession(self.config, "cooperative", "fixed-priority")
            agent_id = sorted(session.agents)[0]
            agent = session.agents[agent_id]
            destination = [agent.x + 1.0, agent.y]
            accepted = session.apply_intervention(
                "set_uav_destination", {"agent_id": agent_id, "destination": destination},
            )
            self.assertTrue(accepted["accepted"])
            self.assertEqual(accepted["outcome"], "destination_route_planned")
            self.assertEqual(accepted["result"]["status"], "navigating")
            self.assertEqual(agent.vehicle.final_destination, tuple(destination))

            before = agent.vehicle.final_destination
            busy = session.apply_intervention(
                "set_uav_destination", {"agent_id": agent_id, "destination": [2.0, 2.0]},
            )
            invalid = session.apply_intervention(
                "set_uav_destination", {"agent_id": "missing", "destination": [2.0, 2.0]},
            )
            self.assertFalse(busy["accepted"])
            self.assertFalse(invalid["accepted"])
            self.assertEqual(agent.vehicle.final_destination, before)
            self.assertEqual(len(session.interventions), 3)
            self.assertEqual(
                [event["event_type"] for event in session.observation_events if event["event_type"].startswith("player_intervention_")],
                ["player_intervention_accepted", "player_intervention_rejected", "player_intervention_rejected"],
            )
            results.append((session.interventions, agent.vehicle.final_destination, session.observation_events))
        self.assertEqual(results[0], results[1])

    def test_entity_protection_creates_evidence_task_and_tracks_measurable_status(self):
        session = SimulationSession(self.config, "cooperative", "fixed-priority")
        entity = session.world.evaluator_snapshot()[0]
        owner = session.agents["agent-001"]
        owner.vehicle.x, owner.vehicle.y = entity.x, entity.y
        owner.observe_locally(Observation(
            entity.entity_id, entity.x, entity.y, 0, owner.agent_id,
        ))

        designation = session.apply_intervention("designate_entity_protection", {
            "entity_id": entity.entity_id,
            "radius": 10.0,
            "zone_type": "protection",
        })
        self.assertTrue(designation["accepted"])
        task_id = designation["result"]["task_id"]
        task = session.mission_tasks[task_id]
        self.assertEqual(task.definition.priority, 100)
        updated = session.apply_intervention("designate_entity_protection", {
            "entity_id": entity.entity_id,
            "radius": 8.0,
            "zone_type": "monitoring",
        })
        self.assertTrue(updated["accepted"])
        self.assertEqual(updated["result"]["task_id"], task_id)
        self.assertEqual(task.definition.priority, 5)
        self.assertEqual(task.definition.completion_criteria, {
            "kind": "monitor_entity",
            "entity_id": entity.entity_id,
            "radius": 8.0,
            "minimum_observations": 2,
        })
        self.assertEqual(task.definition.task_type, "search")
        self.assertEqual(len(session.protection_designations), 1)
        self.assertEqual(session.live_metrics()["entity_protection_task_completion_rate"], 0.0)
        self.assertEqual(
            [event["event_type"] for event in session.observation_events if event["event_type"].startswith("entity_protection_zone_")],
            ["entity_protection_zone_created", "entity_protection_zone_updated"],
        )

        for _ in range(2):
            session.advance_tick()
        self.assertEqual(task.status, "completed")
        self.assertEqual(session.live_metrics()["entity_protection_task_completion_rate"], 1.0)
        self.assertEqual(session.live_metrics()["entity_protection_tasks_completed"], 1)
        self.assertEqual(session.snapshot()["world"]["protection_zones"][0]["entity_id"], entity.entity_id)
        self.assertEqual([item["action"] for item in session.interventions], [
            "designate_entity_protection", "designate_entity_protection",
        ])

        removed = session.apply_intervention("remove_entity_protection", {"entity_id": entity.entity_id})
        self.assertTrue(removed["accepted"])
        self.assertEqual(session.snapshot()["world"].get("protection_zones", []), [])

    def test_entity_protection_rejects_unknown_unobserved_and_invalid_requests(self):
        session = SimulationSession(self.config, "independent")
        unknown = session.apply_intervention("designate_entity_protection", {
            "entity_id": "not-an-entity", "radius": 10.0, "zone_type": "monitoring",
        })
        entity = session.world.evaluator_snapshot()[0]
        unseen = session.apply_intervention("designate_entity_protection", {
            "entity_id": entity.entity_id, "radius": 10.0, "zone_type": "monitoring",
        })
        invalid = session.apply_intervention("designate_entity_protection", {
            "entity_id": entity.entity_id, "radius": -1.0, "zone_type": "monitoring",
        })
        self.assertFalse(unknown["accepted"])
        self.assertEqual(unknown["outcome"], "unknown_entity")
        self.assertFalse(unseen["accepted"])
        self.assertEqual(unseen["outcome"], "entity_must_have_a_fresh_known_track")
        self.assertFalse(invalid["accepted"])
        self.assertEqual(invalid["outcome"], "radius_must_be_positive_and_within_world_scale")
        self.assertEqual(len(session.interventions), 3)

    def test_player_reassignment_uses_task_guards_dispatches_route_and_records_result(self):
        config, mission = load_mission("shared_awareness", seed=42)
        definitions = parse_task_definitions(
            mission["tasks"][:2], config.world_width, config.world_height, config.steps,
        )
        session = SimulationSession(config, "cooperative", "fixed-priority", mission_tasks=definitions)
        session.assign_pending_mission_tasks()
        session.run_autonomous_behaviors()
        task = next(iter(session.mission_tasks.values()))
        new_agent_id = next(
            agent_id for agent_id, agent in sorted(session.agents.items())
            if agent.vehicle.current_task_id is None
        )

        accepted = session.apply_intervention(
            "reassign_mission_task", {"task_id": task.definition.task_id, "agent_id": new_agent_id},
        )
        self.assertTrue(accepted["accepted"])
        self.assertEqual(task.assigned_agent_id, new_agent_id)
        self.assertEqual(task.status, "navigating")
        self.assertEqual(session.agents[new_agent_id].vehicle.current_task_id, task.definition.task_id)
        self.assertEqual(accepted["outcome"], "mission_task_reassigned_and_route_dispatched")
        self.assertTrue(accepted["result"])
        rejected = session.apply_intervention(
            "reassign_mission_task", {"task_id": task.definition.task_id, "agent_id": new_agent_id},
        )
        self.assertFalse(rejected["accepted"])
        self.assertEqual(len(session.interventions), 2)
        self.assertEqual(
            [event["event_type"] for event in session.observation_events if event["event_type"].startswith("player_intervention_")],
            ["player_intervention_accepted", "player_intervention_rejected"],
        )

    def test_saved_cooperative_baseline_summary_and_events_are_preserved(self):
        # The bundled baseline config is the original seed-42 cooperative baseline.
        config = load_config(ROOT / "configs" / "baseline.json")
        actual_summary, actual_events = run_simulation(config, "cooperative")
        expected_summary = json.loads((ROOT / "experiments/results/verification_20261025_0915/baseline_summary.json").read_text(encoding="utf-8"))
        actual_summary["metrics"].pop("wall_clock_runtime_seconds")
        expected_summary["metrics"].pop("wall_clock_runtime_seconds")
        self.assertEqual(actual_summary, expected_summary)
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=EVENT_FIELDS)
        writer.writeheader()
        writer.writerows(actual_events)
        actual_rows = list(csv.DictReader(io.StringIO(stream.getvalue())))
        with (ROOT / "experiments/results/verification_20261025_0915/baseline_events.csv").open(newline="", encoding="utf-8") as event_file:
            expected_rows = list(csv.DictReader(event_file))
        self.assertEqual(actual_rows, expected_rows)


class ProtocolTests(unittest.TestCase):
    def test_protocol_version_malformed_json_and_invalid_command(self):
        server = ProtocolServer()
        malformed = server.handle_line("{\n")
        self.assertFalse(malformed["ok"])
        self.assertEqual(malformed["error"]["code"], "malformed_json")
        missing_version = server.handle_line('{"command":"list_scenarios"}')
        self.assertEqual(missing_version["error"]["code"], "protocol_version_required")
        incompatible = request(server, "list_scenarios", version=77)
        self.assertEqual(incompatible["error"]["code"], "unsupported_protocol_version")
        unknown = request(server, "not_a_command")
        self.assertEqual(unknown["error"]["code"], "unknown_command")

    def test_lifecycle_pause_speed_reset_and_ticks(self):
        server = ProtocolServer()
        start = request(server, "start_run", {"scenario": "shared_awareness", "seed": 12})
        self.assertTrue(start["ok"])
        self.assertEqual(start["result"]["tick"], 0)
        self.assertTrue(request(server, "set_simulation_speed", {"speed": 2})["ok"])
        self.assertEqual(request(server, "set_simulation_speed", {"speed": 3})["error"]["code"], "invalid_speed")
        self.assertTrue(request(server, "pause_run")["ok"])
        self.assertEqual(request(server, "advance_ticks")["error"]["code"], "run_paused")
        paused_snapshot = request(server, "get_snapshot")["result"]
        self.assertEqual(paused_snapshot["status"], "paused")
        self.assertEqual(paused_snapshot["mission"]["status"], "paused")
        self.assertTrue(request(server, "resume_run")["ok"])
        advanced = request(server, "advance_ticks", {"count": 3})
        self.assertEqual(advanced["result"]["tick"], 3)
        agent = request(server, "inspect_agent", {"agent_id": "agent-001"})
        self.assertTrue(agent["ok"])
        self.assertIn("locally_known_tracks", agent["result"])
        reset = request(server, "reset_run")
        self.assertEqual(reset["result"]["tick"], 0)
        self.assertEqual(server.session.current_step, 0)
        self.assertEqual(server.session.scheduler.tasks, [])
        self.assertEqual(server.session.interventions, [])
        self.assertTrue(all(not agent.tracks for agent in server.session.agents.values()))

    def test_snapshot_exposes_live_mission_progress_and_track_provenance(self):
        server = ProtocolServer()
        request(server, "start_run", {"scenario": "shared_awareness", "seed": 42})
        response = request(server, "advance_ticks", {"count": 1})
        snapshot = response["result"]["snapshot"]

        self.assertEqual(snapshot["mission"]["id"], "shared_awareness")
        self.assertEqual(snapshot["mission"]["status"], "running")
        self.assertEqual(len(snapshot["mission"]["objectives"]), 2)
        self.assertEqual(len(snapshot["mission"]["tasks"]), 4)
        self.assertTrue(all(task["status"] in {"navigating", "executing", "completed"} for task in snapshot["mission"]["tasks"]))
        self.assertEqual(len({task["assigned_agent_id"] for task in snapshot["mission"]["tasks"]}), 4)
        for objective in snapshot["mission"]["objectives"]:
            self.assertEqual(objective["actual"], snapshot["metrics"][objective["metric"]])
            self.assertIn("target", objective)
        self.assertEqual(snapshot["metrics"]["communication_status"], "available")
        self.assertIn("pending_message_links", snapshot)
        self.assertIsInstance(snapshot["pending_message_links"], list)
        tracks = snapshot["world"]["tracks"]
        self.assertTrue(tracks)
        self.assertTrue(all("source_agent_id" in track for track in tracks))

    def test_autonomous_routes_cross_protocol_snapshot_and_reset_replays_fixed_tick(self):
        server = ProtocolServer()
        started = request(server, "start_run", {"scenario": "shared_awareness", "seed": 42})
        self.assertEqual(started["version"], 1)
        initial = request(server, "get_snapshot")["result"]
        initial_positions = {
            agent["id"]: (agent["x"], agent["y"])
            for agent in initial["world"]["agents"]
        }
        routed_agents = [
            agent for agent in initial["world"]["agents"]
            if agent.get("current_task_id") and agent.get("final_destination") is not None
        ]
        self.assertEqual(len(routed_agents), 4)
        self.assertTrue(all(task["status"] == "navigating" for task in initial["mission"]["tasks"]))

        first_tick = request(server, "advance_ticks", {"count": 1})["result"]
        self.assertEqual(first_tick["tick"], 1)
        self.assertTrue(any(
            event["event_type"] in {"uav_moved", "uav_arrived"}
            for event in first_tick["events"]
        ))
        self.assertTrue(any(
            (agent["x"], agent["y"]) != initial_positions[agent["id"]]
            for agent in first_tick["snapshot"]["world"]["agents"]
        ))
        inspected = request(server, "inspect_agent", {"agent_id": routed_agents[0]["id"]})["result"]
        self.assertIsNotNone(inspected["motion"]["current_task_id"])
        self.assertTrue(inspected["mission_tasks"])
        self.assertEqual(inspected["mission_tasks"][0]["assigned_agent_id"], routed_agents[0]["id"])
        self.assertEqual(inspected["mission_tasks"][0]["status"], "navigating")

        reset = request(server, "reset_run")
        self.assertEqual(reset["result"]["tick"], 0)
        replay = request(server, "advance_ticks", {"count": 1})["result"]
        self.assertEqual(replay["snapshot"]["world"], first_tick["snapshot"]["world"])
        self.assertEqual(replay["snapshot"]["mission"]["tasks"], first_tick["snapshot"]["mission"]["tasks"])

        independent = ProtocolServer()
        request(independent, "start_run", {"scenario": "shared_awareness", "seed": 42, "mode": "independent"})
        isolated_snapshot = request(independent, "advance_ticks")["result"]["snapshot"]
        self.assertEqual(isolated_snapshot["metrics"]["communication_status"], "peer_sharing_disabled")

    def test_subprocess_starts_handles_lines_and_shuts_down(self):
        process = subprocess.Popen(
            [sys.executable, "-u", "-m", "swarmshield.protocol"],
            cwd=ROOT,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write("{\n")
        process.stdin.flush()
        malformed = json.loads(process.stdout.readline())
        self.assertEqual(malformed["error"]["code"], "malformed_json")
        process.stdin.write(json.dumps({"version": 1, "request_id": "list", "command": "list_scenarios", "payload": {}}) + "\n")
        process.stdin.flush()
        response = json.loads(process.stdout.readline())
        self.assertEqual(response["request_id"], "list")
        self.assertEqual(set(response["result"]["scenarios"]), {"shared_awareness", "deadline_pressure", "network_recovery"})
        process.stdin.write(json.dumps({"version": 1, "request_id": "stop", "command": "shutdown", "payload": {}}) + "\n")
        process.stdin.flush()
        shutdown = json.loads(process.stdout.readline())
        self.assertEqual(shutdown["result"]["status"], "shutdown")
        process.stdin.close()
        self.assertEqual(process.wait(timeout=3), 0)
        process.stdout.close()
        assert process.stderr is not None
        process.stderr.close()

    def test_run_artifacts_and_real_mission_result(self):
        server = ProtocolServer()
        with TemporaryDirectory() as directory, patch("swarmshield.missions.RUNS_DIR", Path(directory)):
            request(server, "start_run", {"scenario": "shared_awareness", "seed": 42})
            request(server, "advance_ticks", {"count": 100})
            self.assertTrue(server.session.finished)
            self.assertTrue(server.artifact_path)
            run_dir = Path(server.artifact_path)
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
            with (run_dir / "events.csv").open(newline="", encoding="utf-8") as event_file:
                saved_events = list(csv.DictReader(event_file))
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["actual_steps"], 100)
            self.assertEqual(summary["game_result"]["mission"]["status"], "success")
            self.assertIsNotNone(summary["game_result"]["score"]["total_score"])
            assignment_events = [event for event in saved_events if event["event_type"] == "mission_task_assigned"]
            self.assertEqual(len(assignment_events), 4)
            self.assertTrue(all(event["resource_id"] for event in assignment_events))
            self.assertEqual(
                summary["game_result"]["mission"],
                evaluate_mission(server.mission, summary["metrics"], completed=True),
            )
            self.assertEqual(
                summary["game_result"]["score"],
                calculate_score(summary["metrics"], server.mission["scoring_weights"]),
            )
            for objective in summary["game_result"]["mission"]["objectives"]:
                self.assertEqual(objective["actual"], summary["metrics"][objective["metric"]])
            with (run_dir / "events.csv").open(newline="", encoding="utf-8") as event_file:
                rows = list(csv.DictReader(event_file))
            self.assertTrue(any(row["event_type"] == "simulation_snapshot" for row in rows))
            interventions = json.loads((run_dir / "interventions.json").read_text(encoding="utf-8"))
            self.assertEqual(interventions["interventions"], [])

    def test_supported_and_rejected_interventions_are_logged(self):
        server = ProtocolServer()
        request(server, "start_run", {"scenario": "shared_awareness", "seed": 2})
        accepted = request(server, "apply_intervention", {"action": "set_scheduler_policy", "parameters": {"policy": "edf"}})
        rejected = request(server, "apply_intervention", {"action": "set_scheduler_policy", "parameters": {"policy": "random"}})
        self.assertTrue(accepted["result"]["accepted"])
        self.assertFalse(rejected["result"]["accepted"])
        self.assertEqual(len(server.session.interventions), 2)
        self.assertEqual(server.session.scheduler.policy, "edf")

    def test_protection_intervention_adds_mission_objective_and_saves_definition(self):
        server = ProtocolServer()
        with TemporaryDirectory() as directory, patch("swarmshield.missions.RUNS_DIR", Path(directory)):
            request(server, "start_run", {"scenario": "shared_awareness", "seed": 42})
            entity = server.session.world.evaluator_snapshot()[0]
            agent = server.session.agents["agent-001"]
            agent.observe_locally(Observation(entity.entity_id, entity.x, entity.y, 0, agent.agent_id))

            response = request(server, "apply_intervention", {
                "action": "designate_entity_protection",
                "parameters": {"entity_id": entity.entity_id, "radius": 12.0, "zone_type": "monitoring"},
            })
            self.assertTrue(response["result"]["accepted"])
            snapshot = server._snapshot()
            protection_objectives = [
                objective for objective in snapshot["mission"]["objectives"]
                if objective["metric"] == "entity_protection_task_completion_rate"
            ]
            self.assertEqual(len(protection_objectives), 1)
            self.assertEqual(protection_objectives[0]["actual"], 0.0)
            self.assertEqual(len(snapshot["world"]["protection_zones"]), 1)

            ended = request(server, "end_run")
            run_dir = Path(ended["result"]["artifact_path"])
            saved_mission = json.loads((run_dir / "scenario.json").read_text())
            self.assertTrue(any(task["task_id"].startswith("protection-") for task in saved_mission["mission"]["tasks"]))
            self.assertTrue(any(
                objective["metric"] == "entity_protection_task_completion_rate"
                for objective in saved_mission["mission"]["objectives"]
            ))
            actions = json.loads((run_dir / "interventions.json").read_text())["interventions"]
            self.assertEqual([action["action"] for action in actions], ["designate_entity_protection"])

    def test_protocol_records_destination_and_reassignment_actions_in_run_artifact(self):
        server = ProtocolServer()
        with TemporaryDirectory() as directory, patch("swarmshield.missions.RUNS_DIR", Path(directory)):
            request(server, "start_run", {"scenario": "shared_awareness", "seed": 42})
            tasks = sorted(server.session.mission_tasks.values(), key=lambda task: task.definition.task_id)
            self.assertEqual(len(tasks), 4)
            available_agent_id = tasks[1].assigned_agent_id
            destination_agent_id = tasks[2].assigned_agent_id
            server.session.cancel_mission_task(tasks[1].definition.task_id)
            server.session.cancel_mission_task(tasks[2].definition.task_id)

            reassigned = request(server, "apply_intervention", {
                "action": "reassign_mission_task",
                "parameters": {"task_id": tasks[0].definition.task_id, "agent_id": available_agent_id},
            })
            self.assertTrue(reassigned["result"]["accepted"])
            self.assertEqual(tasks[0].assigned_agent_id, available_agent_id)
            destination_agent = server.session.agents[destination_agent_id]
            destination = [destination_agent.x, destination_agent.y]
            routed = request(server, "apply_intervention", {
                "action": "set_uav_destination",
                "parameters": {"agent_id": destination_agent_id, "destination": destination},
            })
            rejected = request(server, "apply_intervention", {
                "action": "set_uav_destination",
                "parameters": {"agent_id": "missing-agent", "destination": destination},
            })
            self.assertTrue(routed["result"]["accepted"])
            self.assertFalse(rejected["result"]["accepted"])
            self.assertEqual(len(server.session.interventions), 3)

            ended = request(server, "end_run")
            artifact = Path(ended["result"]["artifact_path"])
            saved = json.loads((artifact / "interventions.json").read_text(encoding="utf-8"))
            self.assertEqual([item["action"] for item in saved["interventions"]], [
                "reassign_mission_task", "set_uav_destination", "set_uav_destination",
            ])
            self.assertEqual([item["accepted"] for item in saved["interventions"]], [True, True, False])

    def test_early_end_marks_run_incomplete_and_eof_finalization_saves(self):
        server = ProtocolServer()
        with TemporaryDirectory() as directory, patch("swarmshield.missions.RUNS_DIR", Path(directory)):
            request(server, "start_run", {"scenario": "shared_awareness", "seed": 5})
            request(server, "advance_ticks", {"count": 2})
            result = request(server, "end_run")
            self.assertEqual(result["result"]["status"], "incomplete")
            self.assertEqual(result["result"]["summary"]["game_result"]["mission"]["status"], "incomplete")
            self.assertTrue(Path(result["result"]["artifact_path"]).is_dir())

            request(server, "start_run", {"scenario": "shared_awareness", "seed": 6})
            server.finalize_on_exit()
            self.assertTrue(server.session.finished)
            self.assertTrue(Path(server.artifact_path).is_dir())

    def test_speed_and_tick_request_batching_do_not_change_results(self):
        completed = []
        with TemporaryDirectory() as directory, patch("swarmshield.missions.RUNS_DIR", Path(directory)):
            for speed, batch_size in ((0.25, 100), (4.0, 1)):
                server = ProtocolServer()
                request(server, "start_run", {"scenario": "shared_awareness", "seed": 42})
                request(server, "set_simulation_speed", {"speed": speed})
                remaining = 100
                while remaining:
                    count = min(batch_size, remaining)
                    response = request(server, "advance_ticks", {"count": count})
                    self.assertTrue(response["ok"])
                    remaining -= response["result"]["advanced"]
                summary = dict(server.session.summary)
                summary["metrics"] = dict(summary["metrics"])
                summary["metrics"].pop("wall_clock_runtime_seconds")
                completed.append((summary, server.session.events))
        self.assertEqual(completed[0], completed[1])


class MissionScoringTests(unittest.TestCase):
    def test_all_three_missions_use_actual_engine_metrics(self):
        for scenario_id in ("shared_awareness", "deadline_pressure", "network_recovery"):
            config, mission = load_mission(scenario_id, seed=42)
            summary, _ = run_simulation(config, "cooperative")
            result = evaluate_mission(mission, summary["metrics"], completed=True)
            self.assertEqual(len(result["objectives"]), 2)
            self.assertEqual(result["status"], "success")
        config, _ = load_mission("network_recovery", seed=42)
        summary, events = run_simulation(config, "cooperative")
        self.assertEqual(summary["metrics"]["recovery_time_steps"], 6)
        event_types = {event["event_type"] for event in events}
        self.assertIn("communication_partition_started", event_types)
        self.assertIn("communication_restored", event_types)

    def test_scoring_is_transparent_and_handles_unavailable_dimensions(self):
        score = calculate_score({
            "any_agent_awareness_coverage": 0.8,
            "deadline_miss_rate": 0.25,
            "message_delivery_ratio": None,
            "task_completion_rate": 0.5,
        })
        self.assertEqual(score["total_score"], 72.0)
        self.assertIsNone(score["components"]["reliability"]["normalized_value"])
        self.assertAlmostEqual(score["components"]["awareness"]["effective_weight"], 0.4)
        incomplete = evaluate_mission(
            {"objectives": [{"metric": "coverage", "operator": ">=", "target": 0}]},
            {"coverage": 1.0},
            completed=False,
        )
        self.assertEqual(incomplete["status"], "incomplete")

    def test_unmet_mission_objectives_include_actual_metric_guidance(self):
        mission = {
            "objectives": [
                {"id": "coverage", "label": "Coverage", "metric": "any_agent_awareness_coverage", "operator": ">=", "target": 0.5},
                {"id": "completion", "label": "Completion", "metric": "task_completion_rate", "operator": ">=", "target": 0.7},
                {"id": "deadlines", "label": "Deadlines", "metric": "deadline_miss_rate", "operator": "<=", "target": 0.2},
                {"id": "recovery", "label": "Recovery", "metric": "recovery_time_steps", "operator": "<=", "target": 20},
            ]
        }
        result = evaluate_mission(mission, {
            "any_agent_awareness_coverage": 0.25,
            "task_completion_rate": 0.5,
            "deadline_miss_rate": 0.4,
            "recovery_time_steps": None,
        }, completed=False)

        self.assertEqual(result["status"], "incomplete")
        self.assertIn("25.0 percentage points", result["objectives"][0]["guidance"])
        self.assertIn("Apply scheduler", result["objectives"][1]["guidance"])
        self.assertIn("Apply scheduler", result["objectives"][2]["guidance"])
        self.assertIn("No recovery time has been measured", result["objectives"][3]["guidance"])


if __name__ == "__main__":
    unittest.main()
