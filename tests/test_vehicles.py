import json
import math
import unittest

from swarmshield.config import SimulationConfig, UAVConfig
from swarmshield.geometry import world_geometry_from_dict
from swarmshield.session import SimulationSession
from swarmshield.vehicles import UAVState
from swarmshield.world import World


class UAVMotionTests(unittest.TestCase):
    def make_world(self, **kwargs):
        return World(SimulationConfig(
            world_width=20,
            world_height=20,
            observer_count=1,
            entity_count=1,
            **kwargs,
        ), seed=29)

    def test_motion_respects_acceleration_speed_and_turn_limits(self):
        world = self.make_world()
        config = UAVConfig(
            max_speed=2.0,
            acceleration=0.5,
            max_turn_rate_rad=0.25,
            battery_capacity=20.0,
            energy_per_distance=1.0,
        )
        uav = UAVState("uav-a", 5.0, 5.0, 0.0, config)
        uav.set_destination((5.0, 15.0), world)

        first = uav.advance(world)
        second = uav.advance(world)

        self.assertAlmostEqual(first.speed, 0.5)
        self.assertAlmostEqual(second.speed, 1.0)
        self.assertAlmostEqual(first.heading_rad, 0.25)
        self.assertAlmostEqual(second.heading_rad, 0.5)
        self.assertLessEqual(uav.speed, config.max_speed)
        self.assertLess(uav.battery_remaining, config.battery_capacity)
        self.assertGreater(uav.distance_travelled, 0.0)

    def test_arrival_stops_at_destination(self):
        world = self.make_world()
        uav = UAVState(
            "uav-a", 5.0, 5.0, 0.0,
            UAVConfig(max_speed=2.0, acceleration=2.0, max_turn_rate_rad=1.0),
        )
        uav.set_destination((7.0, 5.0), world)

        result = uav.advance(world)

        self.assertEqual(result.status, "arrived")
        self.assertEqual(result.position, (7.0, 5.0))
        self.assertIsNone(uav.destination)
        self.assertEqual(uav.speed, 0.0)

    def test_motion_stops_before_solid_geometry(self):
        world = World(SimulationConfig(
            world_width=20,
            world_height=20,
            observer_count=1,
            entity_count=1,
            geometry=world_geometry_from_dict({
                "obstacles": [{
                    "id": "wall",
                    "kind": "wall",
                    "vertices": [[8, 5], [10, 5], [10, 15], [8, 15]],
                }],
            }),
        ), seed=29)
        uav = UAVState(
            "uav-a", 6.0, 10.0, 0.0,
            UAVConfig(max_speed=3.0, acceleration=3.0, max_turn_rate_rad=1.0),
        )
        uav.set_destination((14.0, 10.0), world)

        result = uav.advance(world)

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.position, (6.0, 10.0))
        self.assertFalse(world.is_navigable((8.0, 10.0)))

    def test_energy_budget_stops_and_marks_uav_unavailable(self):
        world = self.make_world()
        uav = UAVState(
            "uav-a", 5.0, 5.0, 0.0,
            UAVConfig(
                max_speed=3.0,
                acceleration=3.0,
                max_turn_rate_rad=1.0,
                battery_capacity=1.0,
                energy_per_distance=1.0,
            ),
        )
        uav.set_destination((15.0, 5.0), world)

        result = uav.advance(world)

        self.assertAlmostEqual(result.distance_moved, 1.0)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.battery_remaining, 0.0)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            uav.set_destination((4.0, 5.0), world)

    def test_destination_validation_rejects_bad_coordinates(self):
        world = self.make_world()
        uav = UAVState("uav-a", 5.0, 5.0, 0.0, UAVConfig())
        for destination in ((21, 5), (math.nan, 5), (True, 5), ("x", 5), (5,)):
            with self.subTest(destination=destination):
                with self.assertRaises(ValueError):
                    uav.set_destination(destination, world)

    def test_session_moves_only_commanded_uav_and_records_reproducible_state(self):
        config = SimulationConfig(
            seed=31,
            steps=3,
            world_width=20,
            world_height=20,
            observer_count=2,
            entity_count=1,
            detection_probability=0.0,
            uav=UAVConfig(max_speed=2.0, acceleration=0.5, max_turn_rate_rad=1.0),
        )
        runs = []
        for _ in range(2):
            session = SimulationSession(config, "independent")
            moving = session.agents["agent-001"]
            stationary = session.agents["agent-002"]
            start = (moving.x, moving.y)
            other_start = (stationary.x, stationary.y)
            moving.set_destination((moving.x - 4.0, moving.y), session.world, task_id="task-demo")

            snapshot = session.advance_tick()

            self.assertEqual(session.current_step, 1)
            self.assertNotEqual((moving.x, moving.y), start)
            self.assertEqual((stationary.x, stationary.y), other_start)
            self.assertEqual(snapshot["agents"][0]["x"], moving.x)
            self.assertEqual(snapshot["agents"][0]["uav_status"], "navigating")
            self.assertEqual(moving.vehicle.current_task_id, "task-demo")
            inspected = session.inspect_agent(moving.agent_id)
            self.assertEqual(inspected["sensor_config"]["detection_range"], config.detection_range)
            self.assertIn("communication", inspected)
            motion_events = [event for event in session.observation_events if event["event_type"] == "uav_moved"]
            self.assertEqual(len(motion_events), 1)
            self.assertEqual(motion_events[0]["sender_id"], moving.agent_id)
            self.assertGreater(json.loads(motion_events[0]["details"])["distance_moved"], 0.0)
            runs.append((snapshot, session.observation_events))
        self.assertEqual(runs[0], runs[1])


if __name__ == "__main__":
    unittest.main()
