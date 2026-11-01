import unittest

from swarmshield.config import config_from_dict


class ConfigTests(unittest.TestCase):
    def test_parses_scheduler_and_coordination_sections(self):
        config = config_from_dict(
            {
                "world": {"steps": 5},
                "scheduler": {"policy": "edf", "queue_capacity": 8},
                "coordination": {"mode": "decentralized", "task_capacity_per_resource": 3},
            }
        )
        self.assertEqual(config.scheduler_policy, "edf")
        self.assertEqual(config.queue_capacity, 8)
        self.assertEqual(config.coordination_mode, "decentralized")
        self.assertEqual(config.task_capacity_per_resource, 3)

    def test_rejects_non_object_config_section(self):
        with self.assertRaisesRegex(ValueError, "scheduler must be a JSON object"):
            config_from_dict({"scheduler": []})

    def test_rejects_invalid_probability_and_policy(self):
        with self.assertRaisesRegex(ValueError, "detection_probability"):
            config_from_dict({"observation": {"detection_probability": 1.5}})
        with self.assertRaisesRegex(ValueError, "scheduler.policy"):
            config_from_dict({"scheduler": {"policy": "random"}})

    def test_parses_and_validates_scenario_geometry(self):
        config = config_from_dict({
            "world": {"width": 20, "height": 20},
            "geometry": {
                "obstacles": [{
                    "id": "hangar-1",
                    "kind": "building",
                    "vertices": [[4, 4], [8, 4], [8, 8], [4, 8]],
                }],
                "buildings": [{
                    "id": "roof-1",
                    "kind": "residential_building",
                    "vertices": [[1, 12], [4, 12], [4, 15], [1, 15]],
                    "blocks_line_of_sight": True,
                }],
                "roads": [{
                    "id": "road-1",
                    "kind": "road",
                    "vertices": [[0, 9], [20, 9], [20, 12], [0, 12]],
                }],
                "paths": [{
                    "id": "path-1",
                    "kind": "footpath",
                    "vertices": [[10, 1], [11, 1], [11, 4], [10, 4]],
                }],
                "parking_areas": [{
                    "id": "parking-1",
                    "kind": "parking",
                    "vertices": [[12, 4], [17, 4], [17, 7], [12, 7]],
                }],
                "water_bodies": [{
                    "id": "pond-1",
                    "kind": "water",
                    "vertices": [[12, 12], [16, 12], [16, 16], [12, 16]],
                }],
                "safe_areas": [{
                    "id": "safe-1",
                    "kind": "recovery-zone",
                    "vertices": [[1, 1], [3, 1], [3, 3], [1, 3]],
                }],
                "points_of_interest": [{"id": "poi-1", "kind": "search", "x": 15, "y": 15}],
            },
        })

        serialized = config.to_dict()["geometry"]
        self.assertEqual(serialized["obstacles"][0]["id"], "hangar-1")
        self.assertTrue(serialized["obstacles"][0]["blocks_line_of_sight"])
        self.assertEqual(serialized["buildings"][0]["kind"], "residential_building")
        self.assertTrue(serialized["buildings"][0]["blocks_line_of_sight"])
        self.assertEqual(serialized["roads"][0]["kind"], "road")
        self.assertEqual(serialized["paths"][0]["kind"], "footpath")
        self.assertEqual(serialized["parking_areas"][0]["kind"], "parking")
        self.assertEqual(serialized["water_bodies"][0]["kind"], "water")
        self.assertEqual(serialized["safe_areas"][0]["id"], "safe-1")
        self.assertEqual(serialized["points_of_interest"][0]["x"], 15.0)

    def test_rejects_out_of_bounds_and_duplicate_geometry(self):
        with self.assertRaisesRegex(ValueError, "within the world bounds"):
            config_from_dict({
                "world": {"width": 10, "height": 10},
                "geometry": {"obstacles": [{
                    "id": "outside",
                    "kind": "building",
                    "vertices": [[1, 1], [12, 1], [12, 5], [1, 5]],
                }]},
            })
        with self.assertRaisesRegex(ValueError, "must be unique"):
            config_from_dict({
                "geometry": {
                    "obstacles": [{
                        "id": "same",
                        "kind": "building",
                        "vertices": [[1, 1], [3, 1], [3, 3], [1, 3]],
                    }],
                    "roads": [{
                        "id": "same",
                        "kind": "road",
                        "vertices": [[1, 4], [3, 4], [3, 5], [1, 5]],
                    }],
                "water_bodies": [{
                    "id": "pond",
                    "kind": "water",
                    "vertices": [[5, 4], [7, 4], [7, 6], [5, 6]],
                }],
                "parking_areas": [{
                    "id": "parking",
                    "kind": "parking",
                    "vertices": [[5, 7], [9, 7], [9, 9], [5, 9]],
                }],
                "paths": [{
                    "id": "footpath",
                    "kind": "path",
                    "vertices": [[10, 4], [11, 4], [11, 9], [10, 9]],
                }],
                },
            })

    def test_loads_named_map_preset_and_rejects_invalid_reference(self):
        config = config_from_dict({"map_preset": "reconnaissance_training_range"})
        self.assertEqual(len(config.geometry.obstacles), 5)
        self.assertEqual(len(config.geometry.buildings), 8)
        self.assertEqual(len(config.geometry.roads), 6)
        self.assertEqual(len(config.geometry.paths), 2)
        self.assertEqual(len(config.geometry.parking_areas), 2)
        self.assertEqual(len(config.geometry.water_bodies), 1)
        self.assertEqual(len(config.geometry.vegetation), 5)
        self.assertEqual(len(config.geometry.caution_zones), 1)
        self.assertEqual(len(config.geometry.mission_areas), 4)
        self.assertEqual(len(config.geometry.points_of_interest), 4)
        with self.assertRaisesRegex(ValueError, "map_preset must be a map identifier"):
            config_from_dict({"map_preset": "../outside"})
        with self.assertRaisesRegex(ValueError, "either map_preset or inline geometry"):
            config_from_dict({"map_preset": "reconnaissance_training_range", "geometry": {}})

    def test_parses_and_validates_uav_motion_limits(self):
        config = config_from_dict({
            "uav": {
                "max_speed": 3.5,
                "acceleration": 0.75,
                "max_turn_rate_rad": 0.4,
                "battery_capacity": 200.0,
                "energy_per_distance": 1.5,
            },
        })
        self.assertEqual(config.uav.max_speed, 3.5)
        self.assertEqual(config.uav.max_turn_rate_rad, 0.4)
        self.assertEqual(config.to_dict()["uav"]["battery_capacity"], 200.0)
        with self.assertRaisesRegex(ValueError, "uav.max_speed"):
            config_from_dict({"uav": {"max_speed": 0}})

    def test_parses_and_validates_sensor_fov_and_line_of_sight(self):
        config = config_from_dict({
            "observation": {"field_of_view_degrees": 120, "require_line_of_sight": False},
        })
        self.assertEqual(config.field_of_view_degrees, 120.0)
        self.assertFalse(config.require_line_of_sight)
        self.assertEqual(config.to_dict()["field_of_view_degrees"], 120.0)
        self.assertFalse(config.to_dict()["require_line_of_sight"])
        default_config = config_from_dict({})
        self.assertNotIn("field_of_view_degrees", default_config.to_dict())
        self.assertNotIn("require_line_of_sight", default_config.to_dict())
        with self.assertRaisesRegex(ValueError, "field_of_view_degrees"):
            config_from_dict({"observation": {"field_of_view_degrees": 361}})
        with self.assertRaisesRegex(ValueError, "require_line_of_sight must be boolean"):
            config_from_dict({"observation": {"require_line_of_sight": "false"}})

    def test_parses_and_validates_network_range_capacity_expiry_and_retries(self):
        config = config_from_dict({
            "network": {
                "communication_range": 12.5,
                "message_queue_capacity": 7,
                "message_ttl_steps": 4,
                "max_message_retries": 2,
            },
        })
        self.assertEqual(config.communication_range, 12.5)
        self.assertEqual(config.message_queue_capacity, 7)
        self.assertEqual(config.message_ttl_steps, 4)
        self.assertEqual(config.max_message_retries, 2)
        serialized = config.to_dict()
        self.assertEqual(serialized["communication_range"], 12.5)
        self.assertEqual(serialized["message_queue_capacity"], 7)
        self.assertEqual(serialized["message_ttl_steps"], 4)
        self.assertEqual(serialized["max_message_retries"], 2)
        defaults = config_from_dict({})
        self.assertNotIn("communication_range", defaults.to_dict())
        self.assertNotIn("message_queue_capacity", defaults.to_dict())
        self.assertNotIn("message_ttl_steps", defaults.to_dict())
        self.assertNotIn("max_message_retries", defaults.to_dict())
        for network, message in (
            ({"communication_range": 0}, "communication_range"),
            ({"message_queue_capacity": 0}, "message_queue_capacity"),
            ({"message_ttl_steps": -1}, "message_ttl_steps"),
            ({"max_message_retries": -1}, "max_message_retries"),
        ):
            with self.subTest(network=network), self.assertRaisesRegex(ValueError, message):
                config_from_dict({"network": network})


if __name__ == "__main__":
    unittest.main()
