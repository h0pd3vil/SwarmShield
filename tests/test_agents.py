import unittest

from swarmshield.agents import Agent
from swarmshield.observations import Observation
from swarmshield.world import Observer


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.agent = Agent(Observer("agent-a", 0.0, 0.0))

    def test_duplicate_message_is_processed_once(self):
        observation = Observation("entity-1", 2.0, 3.0, 4, "agent-b")
        self.assertEqual(self.agent.receive("message-1", observation), "updated")
        self.assertEqual(self.agent.receive("message-1", observation), "duplicate")
        self.assertEqual(len(self.agent.tracks), 1)

    def test_stale_observation_does_not_replace_new_track(self):
        newer = Observation("entity-1", 8.0, 9.0, 8, "agent-b")
        older = Observation("entity-1", 1.0, 2.0, 3, "agent-c")
        self.assertEqual(self.agent.apply_observation(newer), "updated")
        self.assertEqual(self.agent.apply_observation(older), "stale")
        self.assertEqual(self.agent.tracks["entity-1"].observed_at, 8)

    def test_track_freshness_uses_simulation_steps(self):
        observation = Observation("entity-1", 2.0, 3.0, 4, "agent-b")
        self.agent.apply_observation(observation)
        self.assertEqual(len(self.agent.active_tracks(7, 3)), 1)
        self.assertEqual(len(self.agent.active_tracks(8, 3)), 0)

    def test_track_preserves_provenance_and_confidence_without_leaking_to_other_agents(self):
        other = Agent(Observer("agent-b", 10.0, 10.0))
        observation = Observation("entity-1", 2.5, 3.5, 7, "agent-a", confidence=0.65)

        self.assertEqual(self.agent.observe_locally(observation), "updated")

        self.assertEqual(len(self.agent.tracks), 1)
        self.assertEqual(self.agent.tracks["entity-1"].source_agent_id, "agent-a")
        self.assertEqual(self.agent.tracks["entity-1"].confidence, 0.65)
        self.assertEqual(self.agent.tracks["entity-1"].observed_at, 7)
        self.assertEqual(other.tracks, {})

    def test_repeated_entity_reports_keep_one_track_and_newer_confidence_wins_same_tick(self):
        first = Observation("entity-1", 2.0, 3.0, 4, "agent-a", confidence=0.5)
        weaker = Observation("entity-1", 4.0, 5.0, 4, "agent-b", confidence=0.4)
        stronger = Observation("entity-1", 6.0, 7.0, 4, "agent-c", confidence=0.8)

        self.assertEqual(self.agent.apply_observation(first), "updated")
        self.assertEqual(self.agent.apply_observation(weaker), "unchanged")
        self.assertEqual(self.agent.apply_observation(stronger), "updated")

        self.assertEqual(len(self.agent.tracks), 1)
        self.assertEqual(self.agent.tracks["entity-1"].source_agent_id, "agent-c")
        self.assertEqual(self.agent.tracks["entity-1"].confidence, 0.8)


if __name__ == "__main__":
    unittest.main()
