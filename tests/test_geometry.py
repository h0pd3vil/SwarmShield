import json
import unittest

from swarmshield.config import SimulationConfig, UAVConfig, config_from_dict
from swarmshield.geometry import world_geometry_from_dict
from swarmshield.navigation import GridPathPlanner
from swarmshield.session import SimulationSession
from swarmshield.config import UAVConfig
from swarmshield.world import World


class WorldGeometryTests(unittest.TestCase):
    def setUp(self):
        self.config = config_from_dict({
            "world": {"width": 20, "height": 20},
            "geometry": {
                "obstacles": [{
                    "id": "building",
                    "kind": "building",
                    "vertices": [[8, 8], [12, 8], [12, 12], [8, 12]],
                }],
                "vegetation": [{
                    "id": "tree-belt",
                    "kind": "vegetation",
                    "vertices": [[2, 8], [4, 8], [4, 12], [2, 12]],
                    "blocks_line_of_sight": True,
                }],
                "safe_areas": [{
                    "id": "recovery",
                    "kind": "recovery-zone",
                    "vertices": [[1, 1], [4, 1], [4, 4], [1, 4]],
                }],
                "restricted_regions": [{
                    "id": "restricted",
                    "kind": "restricted",
                    "vertices": [[15, 15], [18, 15], [18, 18], [15, 18]],
                }],
            },
        })
        self.world = World(self.config, seed=17)

    def test_points_and_direct_segments_respect_obstacles_restrictions_and_bounds(self):
        self.assertFalse(self.world.is_navigable((10, 10)))
        self.assertFalse(self.world.is_navigable((8, 10)))  # polygon boundary is blocked
        self.assertFalse(self.world.is_navigable((16, 16)))
        self.assertFalse(self.world.is_navigable((21, 10)))
        self.assertTrue(self.world.is_navigable((6, 10)))

        self.assertFalse(self.world.segment_is_navigable((2, 10), (18, 10)))
        self.assertFalse(self.world.segment_is_navigable((13, 14), (19, 19)))
        self.assertTrue(self.world.segment_is_navigable((2, 6), (18, 6)))

    def test_line_of_sight_uses_configured_occluders(self):
        self.assertFalse(self.world.has_line_of_sight((1, 10), (6, 10)))
        self.assertFalse(self.world.has_line_of_sight((2, 10), (18, 10)))
        self.assertTrue(self.world.has_line_of_sight((2, 6), (18, 6)))

    def test_safe_area_query_is_separate_from_navigation(self):
        self.assertTrue(self.world.is_in_safe_area((2, 2)))
        self.assertTrue(self.world.is_navigable((2, 2)))
        self.assertFalse(self.world.is_in_safe_area((6, 6)))

    def test_restricted_zone_policies_and_agent_authorization(self):
        geometry = {
            "restricted_regions": [{
                "id": "controlled",
                "kind": "restricted",
                "vertices": [[8, 6], [12, 6], [12, 14], [8, 14]],
                "behavior": "deny_entry",
                "authorized_agent_ids": ["agent-001"],
            }],
        }
        config = config_from_dict({
            "world": {"width": 20, "height": 20},
            "geometry": geometry,
        })
        world = World(config, seed=3)
        planner = GridPathPlanner()

        self.assertFalse(world.is_navigable((10, 10), "agent-002"))
        self.assertTrue(world.is_navigable((10, 10), "agent-001"))
        self.assertFalse(world.segment_is_navigable((8, 10), (10, 10), "agent-002"))
        self.assertTrue(world.segment_is_navigable((8, 10), (5, 10), "agent-002"))
        self.assertTrue(world.segment_is_navigable((10, 10), (5, 10), "agent-002"))
        self.assertGreater(planner.plan((5, 10), (15, 10), world, "agent-002").total_distance, 10.0)
        self.assertEqual(planner.plan((5, 10), (15, 10), world, "agent-001").total_distance, 10.0)
        self.assertEqual(config.geometry.to_dict()["restricted_regions"][0]["authorized_agent_ids"], ["agent-001"])

    def test_denied_entry_is_blocked_and_recorded_from_actual_uav_motion(self):
        config = SimulationConfig(
            seed=5,
            steps=12,
            world_width=20,
            world_height=20,
            observer_count=1,
            entity_count=1,
            detection_probability=0.0,
            geometry=world_geometry_from_dict({"restricted_regions": [{
                "id": "controlled", "kind": "restricted",
                "vertices": [[8, 6], [12, 6], [12, 14], [8, 14]],
                "behavior": "deny_entry",
            }]}),
            uav=UAVConfig(max_speed=1.0, acceleration=0.5, max_turn_rate_rad=0.5235987756),
        )
        session = SimulationSession(config, "independent")
        agent = session.agents["agent-001"]
        agent.vehicle.x, agent.vehicle.y = 6.0, 10.0
        agent.vehicle.heading_rad = 0.0
        agent.vehicle.destination = (16.0, 10.0)
        agent.vehicle.final_destination = (16.0, 10.0)
        agent.vehicle.status = "navigating"
        agent.vehicle.has_motion_history = True

        for _ in range(3):
            session.advance_tick()
        denied = [event for event in session.observation_events if event["event_type"] == "restricted_zone_entry_denied"]
        self.assertTrue(denied)
        self.assertEqual(agent.vehicle.position, (7.5, 10.0))
        self.assertEqual(json.loads(denied[0]["details"])["zone_id"], "controlled")

    def test_warn_zone_records_actual_unauthorized_entry_violation(self):
        config = SimulationConfig(
            seed=6,
            steps=12,
            world_width=20,
            world_height=20,
            observer_count=1,
            entity_count=1,
            detection_probability=0.0,
            geometry=world_geometry_from_dict({"restricted_regions": [{
                "id": "monitor-only", "kind": "restricted",
                "vertices": [[8, 6], [12, 6], [12, 14], [8, 14]],
                "behavior": "warn",
            }]}),
            uav=UAVConfig(max_speed=1.0, acceleration=0.5, max_turn_rate_rad=0.5235987756),
        )
        session = SimulationSession(config, "independent")
        agent = session.agents["agent-001"]
        agent.vehicle.x, agent.vehicle.y = 6.0, 10.0
        agent.vehicle.heading_rad = 0.0
        agent.vehicle.destination = (16.0, 10.0)
        agent.vehicle.final_destination = (16.0, 10.0)
        agent.vehicle.status = "navigating"
        agent.vehicle.has_motion_history = True

        for _ in range(6):
            session.advance_tick()
        violations = [event for event in session.observation_events if event["event_type"] == "restricted_zone_violation"]
        self.assertTrue(violations)
        self.assertEqual(agent.vehicle.position, (11.5, 10.0))
        self.assertEqual(json.loads(violations[0]["details"])["policy"], "warn")

    def test_invalid_restricted_zone_policy_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "behavior is unsupported"):
            config_from_dict({
                "world": {"width": 20, "height": 20},
                "geometry": {"restricted_regions": [{
                    "id": "bad-policy", "kind": "restricted",
                    "vertices": [[2, 2], [5, 2], [5, 5], [2, 5]],
                    "behavior": "teleport",
                }]},
            })

    def test_rejects_self_intersecting_polygons(self):
        with self.assertRaisesRegex(ValueError, "must not self-intersect"):
            config_from_dict({
                "world": {"width": 10, "height": 10},
                "geometry": {"obstacles": [{
                    "id": "bow-tie",
                    "kind": "wall",
                    "vertices": [[1, 1], [4, 1], [1, 4], [4, 4]],
                }]},
            })


if __name__ == "__main__":
    unittest.main()
