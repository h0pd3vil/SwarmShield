import random
import math
import unittest

from swarmshield.config import SimulationConfig, UAVConfig
from swarmshield.geometry import world_geometry_from_dict
from swarmshield.observations import EntityView, ObservationModel
from swarmshield.session import SimulationSession
from swarmshield.world import World


class ObservationModelTests(unittest.TestCase):
    def make_model(self, seed=3, **kwargs):
        return ObservationModel(
            rng=random.Random(seed),
            detection_range=20.0,
            detection_probability=1.0,
            position_noise_std=0.0,
            world_width=20.0,
            world_height=20.0,
            **kwargs,
        )

    def test_field_of_view_is_relative_to_current_heading(self):
        model = self.make_model(field_of_view_degrees=90.0)
        entities = (
            EntityView("east", 8.0, 5.0),
            EntityView("north", 5.0, 2.0),
            EntityView("west", 2.0, 5.0),
        )

        reports = model.observe("agent-a", 5.0, 5.0, entities, 4, observer_heading_rad=0.0)

        self.assertEqual([report.entity_id for report in reports], ["east"])

    def test_targets_outside_sensor_range_are_not_detected(self):
        model = ObservationModel(random.Random(3), 5.0, 1.0, 0.0, 20.0, 20.0)
        entities = (EntityView("edge", 8.0, 5.0), EntityView("outside", 8.01, 5.0))

        reports = model.observe("agent-a", 3.0, 5.0, entities, 2)

        self.assertEqual([report.entity_id for report in reports], ["edge"])

    def test_line_of_sight_blocks_only_when_enabled(self):
        geometry = world_geometry_from_dict({
            "obstacles": [{
                "id": "screening-wall",
                "kind": "wall",
                "vertices": [[8, 3], [10, 3], [10, 7], [8, 7]],
            }],
        })
        world = World(SimulationConfig(
            world_width=20,
            world_height=20,
            observer_count=1,
            entity_count=1,
            geometry=geometry,
        ), seed=9)
        entity = EntityView("hidden", 14.0, 5.0)

        blocked = self.make_model(require_line_of_sight=True).observe(
            "agent-a", 5.0, 5.0, (entity,), 1, line_of_sight_test=world.has_line_of_sight,
        )
        visible = self.make_model(require_line_of_sight=False).observe(
            "agent-a", 5.0, 5.0, (entity,), 1, line_of_sight_test=world.has_line_of_sight,
        )

        self.assertEqual(blocked, [])
        self.assertEqual([report.entity_id for report in visible], ["hidden"])

    def test_noise_is_seeded_timestamped_and_clamped_to_world(self):
        entity = EntityView("edge", 0.0, 0.0)
        first = ObservationModel(random.Random(17), 20.0, 1.0, 2.0, 20.0, 20.0)
        second = ObservationModel(random.Random(17), 20.0, 1.0, 2.0, 20.0, 20.0)

        report = first.observe("agent-a", 0.0, 0.0, (entity,), 6)[0]
        repeated = second.observe("agent-a", 0.0, 0.0, (entity,), 6)[0]

        self.assertEqual(report, repeated)
        self.assertEqual((report.observed_at, report.source_agent_id), (6, "agent-a"))
        self.assertAlmostEqual(report.x, 1.7729829446375618)
        self.assertEqual(report.y, 0.0)
        self.assertEqual(report.confidence, 1.0)

    def test_observation_model_accepts_heading_and_los_settings(self):
        world = World(SimulationConfig(
            seed=12,
            world_width=20,
            world_height=20,
            observer_count=1,
            entity_count=1,
            detection_range=20,
            detection_probability=1.0,
            position_noise_std=0.0,
        ), seed=12)
        # The observation API receives only position and heading. This setup
        # verifies that an east-facing 90-degree sensor excludes a northern view.
        model = ObservationModel(random.Random(4), 20.0, 1.0, 0.0, 20.0, 20.0)
        entities = (EntityView("north", 10.0, 2.0), EntityView("east", 15.0, 10.0))
        reports = model.observe(
            "agent-a", 10.0, 10.0, entities, 2,
            observer_heading_rad=0.0,
            line_of_sight_test=world.has_line_of_sight,
            field_of_view_degrees=90.0,
            require_line_of_sight=True,
        )

        self.assertEqual([report.entity_id for report in reports], ["east"])

    def test_enabled_line_of_sight_requires_a_world_query(self):
        with self.assertRaisesRegex(ValueError, "line_of_sight_test is required"):
            self.make_model(require_line_of_sight=True).observe(
                "agent-a", 1.0, 1.0, (EntityView("target", 2.0, 1.0),), 1,
            )

    def test_session_sensing_uses_live_uav_heading_and_fov(self):
        session = SimulationSession(SimulationConfig(
            seed=2,
            steps=3,
            world_width=20,
            world_height=20,
            observer_count=1,
            entity_count=1,
            detection_range=20,
            detection_probability=1.0,
            position_noise_std=0.0,
            field_of_view_degrees=90.0,
        ), "independent")
        agent = session.agents["agent-001"]
        agent.vehicle.x, agent.vehicle.y = 10.0, 10.0
        agent.vehicle.heading_rad = 0.0
        entity = session.world._entities[0]
        entity.x, entity.y, entity.vx, entity.vy = 15.0, 10.0, 0.0, 0.0

        session.advance_tick()
        first_tick_reports = [
            event for event in session.observation_events
            if event["step"] == 1 and event["event_type"] == "observation_created"
        ]
        self.assertEqual([event["entity_id"] for event in first_tick_reports], ["entity-001"])

        entity.x, entity.y = 10.0, 5.0
        session.advance_tick()
        second_tick_reports = [
            event for event in session.observation_events
            if event["step"] == 2 and event["event_type"] == "observation_created"
        ]
        self.assertEqual(second_tick_reports, [])

    def test_session_sensing_applies_world_geometry_occlusion(self):
        geometry = world_geometry_from_dict({
            "obstacles": [{
                "id": "screening-wall",
                "kind": "wall",
                "vertices": [[12, 8], [13, 8], [13, 12], [12, 12]],
            }],
        })
        session = SimulationSession(SimulationConfig(
            seed=2,
            steps=2,
            world_width=20,
            world_height=20,
            observer_count=1,
            entity_count=1,
            detection_range=20,
            detection_probability=1.0,
            position_noise_std=0.0,
            geometry=geometry,
            require_line_of_sight=True,
        ), "independent")
        agent = session.agents["agent-001"]
        agent.vehicle.x, agent.vehicle.y = 10.0, 10.0
        agent.vehicle.heading_rad = 0.0
        entity = session.world._entities[0]
        entity.x, entity.y, entity.vx, entity.vy = 15.0, 10.0, 0.0, 0.0

        session.advance_tick()

        reports = [
            event for event in session.observation_events
            if event["step"] == 1 and event["event_type"] == "observation_created"
        ]
        self.assertEqual(reports, [])

    def test_two_uavs_have_different_local_views_until_one_moves_into_range(self):
        session = SimulationSession(SimulationConfig(
            seed=5,
            steps=12,
            world_width=20,
            world_height=10,
            observer_count=2,
            entity_count=1,
            detection_range=2.5,
            detection_probability=1.0,
            position_noise_std=0.0,
            require_line_of_sight=False,
            uav=UAVConfig(max_speed=1.0, acceleration=1.0, max_turn_rate_rad=1.0),
        ), "independent")
        west = session.agents["agent-001"]
        east = session.agents["agent-002"]
        west.vehicle.x, west.vehicle.y = 2.0, 2.0
        east.vehicle.x, east.vehicle.y = 18.0, 2.0
        east.vehicle.heading_rad = math.pi
        target = session.world._entities[0]
        target.x, target.y, target.vx, target.vy = 10.0, 2.0, 0.0, 0.0

        session.advance_tick()
        self.assertEqual(west.tracks, {})
        self.assertEqual(east.tracks, {})
        start_position = east.vehicle.position
        session.assign_destination(east.agent_id, (10.0, 2.0), task_id="approach-target")
        observations_by_east = []
        for _ in range(10):
            session.advance_tick()
            observations_by_east.extend(
                event for event in session.observation_events
                if event["step"] == session.current_step
                and event["event_type"] == "observation_created"
                and event["sender_id"] == east.agent_id
            )
            if east.tracks:
                break

        self.assertNotEqual(east.vehicle.position, start_position)
        self.assertIn("entity-001", east.tracks)
        self.assertEqual(west.tracks, {})
        self.assertTrue(observations_by_east)


if __name__ == "__main__":
    unittest.main()
