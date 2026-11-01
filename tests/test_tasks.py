import unittest
from dataclasses import replace

from swarmshield.missions import load_mission
from swarmshield.config import SimulationConfig
from swarmshield.session import SimulationSession
from swarmshield.tasks import parse_task_definitions


class MissionTaskModelTests(unittest.TestCase):
    @staticmethod
    def reconnaissance_task(task_id="survey-a", **overrides):
        task = {
            "task_id": task_id,
            "task_type": "reconnaissance",
            "location": [5, 5],
            "region": [[1, 1], [9, 1], [9, 9], [1, 9]],
            "prerequisites": [],
            "priority": 2,
            "deadline_step": 20,
            "estimated_duration_steps": 3,
            "required_capabilities": ["visual_sensor"],
            "completion_criteria": {"kind": "observe_region", "minimum_observations": 1},
        }
        task.update(overrides)
        return task

    def test_spatial_task_round_trips_with_explicit_constraints(self):
        definitions = parse_task_definitions(
            [self.reconnaissance_task()], world_width=20, world_height=20, horizon_steps=30,
        )
        task = definitions[0]
        self.assertEqual(task.task_id, "survey-a")
        self.assertEqual(task.location, (5.0, 5.0))
        self.assertEqual(task.region[0], (1.0, 1.0))
        self.assertEqual(task.priority, 2)
        self.assertEqual(task.deadline_step, 20)
        self.assertEqual(task.estimated_duration_steps, 3)
        self.assertEqual(task.required_capabilities, ("visual_sensor",))
        self.assertEqual(task.completion_criteria["kind"], "observe_region")
        self.assertEqual(task.to_dict()["region"][0], [1.0, 1.0])

    def test_runtime_task_records_start_unassigned_and_are_per_run(self):
        definition = parse_task_definitions(
            [self.reconnaissance_task()], world_width=20, world_height=20, horizon_steps=30,
        )[0]
        config = SimulationConfig(steps=30, observer_count=1, entity_count=1)
        first = SimulationSession(config, "independent", mission_tasks=(definition,))
        second = SimulationSession(config, "independent", mission_tasks=(definition,))

        first.mission_tasks[definition.task_id].status = "assigned"
        first.mission_tasks[definition.task_id].assigned_agent_id = "agent-001"

        self.assertEqual(first.mission_tasks[definition.task_id].to_dict()["status"], "assigned")
        self.assertEqual(second.mission_tasks[definition.task_id].to_dict()["status"], "unassigned")

    def test_rejects_invalid_spatial_data_criteria_and_dependencies(self):
        with self.assertRaisesRegex(ValueError, "within world bounds"):
            parse_task_definitions(
                [self.reconnaissance_task(location=[25, 5])], 20, 20, 30,
            )
        with self.assertRaisesRegex(ValueError, "must not self-intersect"):
            parse_task_definitions(
                [self.reconnaissance_task(region=[[1, 1], [9, 9], [1, 9], [9, 1]])], 20, 20, 30,
            )
        with self.assertRaisesRegex(ValueError, "must be .*observe_region"):
            parse_task_definitions(
                [self.reconnaissance_task(completion_criteria={"kind": "arrive", "arrival_radius": 1})], 20, 20, 30,
            )
        with self.assertRaisesRegex(ValueError, "unknown prerequisite"):
            parse_task_definitions(
                [self.reconnaissance_task(prerequisites=["missing"])], 20, 20, 30,
            )

    def test_rejects_duplicate_and_cyclic_prerequisites(self):
        first = self.reconnaissance_task("survey-a", prerequisites=["survey-b"])
        second = self.reconnaissance_task("survey-b", prerequisites=["survey-a"])
        with self.assertRaisesRegex(ValueError, "contain a cycle"):
            parse_task_definitions([first, second], 20, 20, 30)
        with self.assertRaisesRegex(ValueError, "must be unique"):
            parse_task_definitions([self.reconnaissance_task(), self.reconnaissance_task()], 20, 20, 30)

    def test_bundled_missions_load_four_map_aligned_task_definitions(self):
        for mission_id in ("shared_awareness", "deadline_pressure", "network_recovery"):
            with self.subTest(mission=mission_id):
                config, mission = load_mission(mission_id, seed=10)
                tasks = parse_task_definitions(
                    mission["tasks"], config.world_width, config.world_height, config.steps,
                )
                self.assertEqual(len(tasks), 4)
                self.assertTrue(all(task.task_type == "reconnaissance" for task in tasks))
                self.assertTrue(all(task.region is not None and task.location is not None for task in tasks))
                self.assertEqual(len(config.geometry.mission_areas), 4)

    def test_centralized_assignment_uses_distinct_feasible_agents_and_records_events(self):
        config, mission = load_mission("shared_awareness", seed=42)
        definitions = parse_task_definitions(
            mission["tasks"], config.world_width, config.world_height, config.steps,
        )
        session = SimulationSession(config, "cooperative", mission_tasks=definitions)

        assigned = session.assign_pending_mission_tasks()

        self.assertEqual(len(assigned), 4)
        self.assertEqual(len({event["resource_id"] for event in assigned}), 4)
        self.assertEqual([event["task_id"] for event in assigned], ["survey-west", "survey-east", "survey-north-east", "survey-south-west"])
        self.assertTrue(all(task.status == "assigned" for task in session.mission_tasks.values()))
        self.assertTrue(all(task.event_history for task in session.mission_tasks.values()))
        self.assertTrue(all(
            session.agents[task.assigned_agent_id].vehicle.current_task_id == task_id
            and session.agents[task.assigned_agent_id].vehicle.destination is None
            for task_id, task in session.mission_tasks.items()
        ))
        self.assertEqual(len(session.assign_pending_mission_tasks()), 0, "Repeated allocation must not duplicate active work")
        self.assertEqual(
            [event["event_type"] for event in session.observation_events].count("mission_task_assigned"),
            4,
        )

        limited = SimulationSession(config, "cooperative", mission_tasks=definitions)
        limited.agents.pop("agent-003")
        limited.agents.pop("agent-004")
        limited_assignments = limited.assign_pending_mission_tasks()
        self.assertEqual(len(limited_assignments), 2)
        self.assertEqual(sum(task.status == "unassigned" for task in limited.mission_tasks.values()), 2)
        deferred = next(task for task in limited.mission_tasks.values() if task.status == "unassigned")
        self.assertEqual(deferred.assignment_reason, "agent_busy_or_unavailable")

    def test_assignment_explains_capability_deadline_energy_and_network_limits(self):
        config, mission = load_mission("shared_awareness", seed=42)
        definitions = parse_task_definitions(
            mission["tasks"], config.world_width, config.world_height, config.steps,
        )

        no_sensor = SimulationSession(replace(config, detection_range=0.0), "cooperative", mission_tasks=definitions)
        self.assertEqual(no_sensor.assign_pending_mission_tasks(), [])
        self.assertTrue(all(task.assignment_reason == "capability_mismatch" for task in no_sensor.mission_tasks.values()))

        tight_tasks = tuple(replace(task, deadline_step=1) for task in definitions)
        tight_deadline = SimulationSession(config, "cooperative", mission_tasks=tight_tasks)
        self.assertEqual(tight_deadline.assign_pending_mission_tasks(), [])
        self.assertTrue(all(task.assignment_reason == "deadline_infeasible" for task in tight_deadline.mission_tasks.values()))

        low_energy = SimulationSession(config, "cooperative", mission_tasks=definitions)
        for agent in low_energy.agents.values():
            agent.vehicle.battery_remaining = 0.0
        self.assertEqual(low_energy.assign_pending_mission_tasks(), [])
        self.assertTrue(all(task.assignment_reason == "insufficient_energy_reserve" for task in low_energy.mission_tasks.values()))

        partitioned = SimulationSession(
            replace(config, partition_enabled=True, steps=9), "cooperative", mission_tasks=definitions,
        )
        partitioned.step = 3
        self.assertEqual(partitioned.assign_pending_mission_tasks(), [])
        self.assertTrue(all(task.assignment_reason == "communication_unavailable" for task in partitioned.mission_tasks.values()))


if __name__ == "__main__":
    unittest.main()
