import math
import unittest

from swarmshield.config import SimulationConfig, config_from_dict
from swarmshield.agents import Agent
from swarmshield.geometry import world_geometry_from_dict
from swarmshield.runner import _simulation_snapshot
from swarmshield.world import World


class WorldHeadingTests(unittest.TestCase):
    def test_observers_face_the_protected_zone_without_moving(self):
        world = World(SimulationConfig(seed=7), seed=7)

        for observer in world.observers:
            dx = world.protected_zone.x - observer.x
            dy = world.protected_zone.y - observer.y
            expected = math.atan2(dy, dx)
            self.assertAlmostEqual(observer.heading_rad, expected)

        positions_before = [(observer.x, observer.y) for observer in world.observers]
        headings_before = [observer.heading_rad for observer in world.observers]
        world.advance()
        self.assertEqual(positions_before, [(observer.x, observer.y) for observer in world.observers])
        self.assertEqual(headings_before, [observer.heading_rad for observer in world.observers])

    def test_synthetic_entity_trajectories_are_independent_of_observer_count(self):
        one_observer = World(SimulationConfig(seed=19, observer_count=1), seed=19)
        four_observers = World(SimulationConfig(seed=19, observer_count=4), seed=19)
        initial_observers = [(item.x, item.y) for item in one_observer.observers]
        initial_entities = one_observer.evaluator_snapshot()
        self.assertEqual(initial_entities, four_observers.evaluator_snapshot())

        for _ in range(5):
            one_observer.advance()
            four_observers.advance()
            self.assertEqual(one_observer.evaluator_snapshot(), four_observers.evaluator_snapshot())
        self.assertEqual(initial_observers, [(item.x, item.y) for item in one_observer.observers])
        self.assertNotEqual(initial_entities, one_observer.evaluator_snapshot())

    def test_heading_is_live_presentation_state_only(self):
        world = World(SimulationConfig(seed=7), seed=7)
        agents = {observer.agent_id: Agent(observer) for observer in world.observers}

        archived = _simulation_snapshot(world, agents)
        live = _simulation_snapshot(world, agents, include_presentation_state=True)

        self.assertNotIn("heading_rad", archived["agents"][0])
        self.assertIn("heading_rad", live["agents"][0])

    def test_configured_geometry_is_live_presentation_state(self):
        geometry = world_geometry_from_dict({
            "obstacles": [{
                "id": "hangar-1",
                "kind": "building",
                "vertices": [[4, 4], [8, 4], [8, 8], [4, 8]],
            }],
            "buildings": [{
                "id": "residential-1",
                "kind": "residential_building",
                "vertices": [[10, 4], [14, 4], [14, 8], [10, 8]],
                "blocks_line_of_sight": True,
            }],
            "roads": [{
                "id": "road-1",
                "kind": "arterial",
                "vertices": [[0, 9], [20, 9], [20, 11], [0, 11]],
            }],
            "parking_areas": [{
                "id": "parking-1",
                "kind": "parking",
                "vertices": [[12, 3], [17, 3], [17, 6], [12, 6]],
            }],
            "water_bodies": [{
                "id": "pond-1",
                "kind": "water",
                "vertices": [[12, 13], [17, 13], [17, 17], [12, 17]],
            }],
            "paths": [{
                "id": "path-1",
                "kind": "footpath",
                "vertices": [[1, 12], [2, 12], [2, 18], [1, 18]],
            }],
            "points_of_interest": [{"id": "poi-1", "kind": "search", "x": 12, "y": 12}],
        })
        config = SimulationConfig(world_width=20, world_height=20, geometry=geometry)
        world = World(config, seed=7)
        agents = {observer.agent_id: Agent(observer) for observer in world.observers}

        archived = _simulation_snapshot(world, agents)
        live = _simulation_snapshot(world, agents, include_presentation_state=True)

        self.assertNotIn("geometry", archived)
        self.assertEqual(live["geometry"]["obstacles"][0]["id"], "hangar-1")
        self.assertEqual(live["geometry"]["buildings"][0]["id"], "residential-1")
        self.assertEqual(live["geometry"]["roads"][0]["id"], "road-1")
        self.assertEqual(live["geometry"]["paths"][0]["id"], "path-1")
        self.assertEqual(live["geometry"]["parking_areas"][0]["id"], "parking-1")
        self.assertEqual(live["geometry"]["water_bodies"][0]["id"], "pond-1")
        self.assertEqual(live["geometry"]["points_of_interest"][0]["id"], "poi-1")

    def test_building_footprints_occlude_sensors_without_blocking_overflight(self):
        config = config_from_dict({
            "world": {"width": 20, "height": 20},
            "geometry": {"buildings": [{
                "id": "roof",
                "kind": "residential_building",
                "vertices": [[8, 8], [12, 8], [12, 12], [8, 12]],
                "blocks_line_of_sight": True,
            }]},
        })
        world = World(config, seed=7)
        self.assertTrue(world.is_navigable((10, 10)))
        self.assertTrue(world.segment_is_navigable((2, 10), (18, 10)))
        self.assertFalse(world.has_line_of_sight((2, 10), (18, 10)))


if __name__ == "__main__":
    unittest.main()
