import random
import unittest

from swarmshield.network import Envelope, NetworkSimulator
from swarmshield.observations import Observation


class NetworkTests(unittest.TestCase):
    def test_message_envelope_serializes_version_type_timing_and_provenance(self):
        report = Observation("entity-1", 1.5, 2.5, 3, "agent-source", confidence=0.7)
        envelope = Envelope(
            "msg-00000001",
            "agent-sender",
            "agent-recipient",
            report,
            4,
            7,
            valid_until_step=10,
        )

        self.assertEqual(envelope.created_step, 4)
        self.assertEqual(envelope.message_type, "observation")
        self.assertEqual(envelope.protocol_version, 1)
        self.assertEqual(envelope.provenance, {"source_agent_id": "agent-source", "observed_at": 3})
        self.assertEqual(envelope.to_dict(), {
            "protocol_version": 1,
            "message_id": "msg-00000001",
            "message_type": "observation",
            "sender_id": "agent-sender",
            "recipient_id": "agent-recipient",
            "created_step": 4,
            "delivery_step": 7,
            "valid_until_step": 10,
            "copy_index": 0,
            "attempt": 0,
            "provenance": {"source_agent_id": "agent-source", "observed_at": 3},
            "payload": {
                "entity_id": "entity-1",
                "x": 1.5,
                "y": 2.5,
                "observed_at": 3,
                "source_agent_id": "agent-source",
                "confidence": 0.7,
            },
        })

    def test_envelope_includes_optional_actual_sensor_footprint(self):
        report = Observation(
            "entity-1", 1.5, 2.5, 3, "agent-source",
            sensor_coverage_cells=((2, 3), (4, 5)),
        )
        envelope = Envelope("coverage-message", "agent-source", "agent-recipient", report, 3, 4)
        self.assertEqual(
            envelope.to_dict()["payload"]["sensor_coverage_cells"],
            [[2, 3], [4, 5]],
        )

    def test_message_envelope_rejects_invalid_delivery_and_expiry_ticks(self):
        report = Observation("entity-1", 1.0, 2.0, 1, "agent-a")
        with self.assertRaisesRegex(ValueError, "delivery cannot precede creation"):
            Envelope("m1", "agent-a", "agent-b", report, 3, 2)
        with self.assertRaisesRegex(ValueError, "valid_until_step cannot precede"):
            Envelope("m2", "agent-a", "agent-b", report, 3, 3, valid_until_step=2)

    def test_communication_range_drops_unreachable_peers(self):
        network = NetworkSimulator(
            rng=random.Random(1),
            delivery_probability=1.0,
            max_latency_steps=0,
            duplicate_probability=0.0,
            partition_enabled=False,
            total_steps=10,
            communication_range=5.0,
        )
        report = Observation("entity-1", 1.0, 2.0, 1, "agent-a")

        network.publish(
            "agent-a",
            ("at-range", "out-of-range"),
            report,
            1,
            sender_position=(0.0, 0.0),
            recipient_positions={"at-range": (3.0, 4.0), "out-of-range": (5.01, 0.0)},
        )

        self.assertEqual(network.sent_originals, 2)
        self.assertEqual(network.dropped_originals, 1)
        self.assertEqual(network.pending_messages, 1)
        self.assertEqual(network.events[-1]["details"], "out_of_range")

    def test_queue_capacity_counts_envelopes_and_drops_overflow(self):
        network = NetworkSimulator(
            rng=random.Random(1),
            delivery_probability=1.0,
            max_latency_steps=2,
            duplicate_probability=0.0,
            partition_enabled=False,
            total_steps=10,
            queue_capacity=1,
        )
        report = Observation("entity-1", 1.0, 2.0, 1, "agent-a")

        network.publish("agent-a", ("agent-b", "agent-c"), report, 1)

        self.assertEqual(network.pending_messages, 1)
        self.assertEqual(network.sent_originals, 2)
        self.assertEqual(network.dropped_originals, 1)
        self.assertEqual(network.events[-1]["details"], "queue_capacity")

    def test_duplicate_copy_is_dropped_when_queue_has_room_for_only_original(self):
        network = NetworkSimulator(
            rng=random.Random(1),
            delivery_probability=1.0,
            max_latency_steps=1,
            duplicate_probability=1.0,
            partition_enabled=False,
            total_steps=10,
            queue_capacity=1,
        )
        report = Observation("entity-1", 1.0, 2.0, 1, "agent-a")

        network.publish("agent-a", ("agent-b",), report, 1)

        self.assertEqual(network.pending_messages, 1)
        self.assertEqual(network.duplicate_copies_scheduled, 0)
        self.assertEqual(network.dropped_duplicate_copies, 1)
        self.assertEqual(network.events[-1]["details"], "queue_capacity")
        self.assertEqual(network.events[-1]["copy_index"], 1)

    def test_expired_message_is_removed_before_late_delivery(self):
        network = NetworkSimulator(
            rng=random.Random(1),
            delivery_probability=1.0,
            max_latency_steps=0,
            duplicate_probability=0.0,
            partition_enabled=False,
            total_steps=10,
        )
        report = Observation("entity-1", 1.0, 2.0, 1, "agent-a")
        network._queue.append(Envelope(
            "expired", "agent-a", "agent-b", report, 1, 4, valid_until_step=1,
        ))
        applied = []

        network.deliver_due(2, lambda envelope: applied.append(envelope.message_id) or "queued")

        self.assertEqual(applied, [])
        self.assertEqual(network.pending_messages, 0)
        self.assertEqual(network.expired_originals, 1)
        self.assertEqual(network.events[-1]["event_type"], "message_expired")

    def test_optional_loss_retry_is_recorded_and_uses_same_message_id(self):
        class RetryRng:
            def __init__(self):
                self.draws = iter((0.9, 0.1, 0.9))

            def random(self):
                return next(self.draws)

            @staticmethod
            def randint(low, high):
                return low

        network = NetworkSimulator(
            rng=RetryRng(),
            delivery_probability=0.5,
            max_latency_steps=0,
            duplicate_probability=0.0,
            partition_enabled=False,
            total_steps=10,
            max_retries=1,
        )
        report = Observation("entity-1", 1.0, 2.0, 1, "agent-a")

        network.publish("agent-a", ("agent-b",), report, 1)

        self.assertEqual(network.sent_originals, 1)
        self.assertEqual(network.dropped_originals, 0)
        self.assertEqual(network.message_retries, 1)
        self.assertEqual(network._queue[0].message_id, "msg-00000001")
        self.assertEqual(network._queue[0].attempt, 1)
        self.assertIn("message_retry_attempted", [event["event_type"] for event in network.events])

    def test_retries_stop_at_limit_and_count_one_failed_original(self):
        network = NetworkSimulator(
            rng=random.Random(8),
            delivery_probability=0.0,
            max_latency_steps=0,
            duplicate_probability=0.0,
            partition_enabled=False,
            total_steps=10,
            max_retries=2,
        )
        report = Observation("entity-1", 1.0, 2.0, 1, "agent-a")

        network.publish("agent-a", ("agent-b",), report, 1)

        self.assertEqual(network.sent_originals, 1)
        self.assertEqual(network.dropped_originals, 1)
        self.assertEqual(network.message_retries, 2)
        self.assertEqual(
            [event["event_type"] for event in network.events].count("message_retry_attempted"),
            2,
        )

    def test_configured_ttl_is_stored_on_envelope(self):
        network = NetworkSimulator(
            rng=random.Random(1),
            delivery_probability=1.0,
            max_latency_steps=0,
            duplicate_probability=0.0,
            partition_enabled=False,
            total_steps=10,
            message_ttl_steps=3,
        )
        report = Observation("entity-1", 1.0, 2.0, 1, "agent-a")

        network.publish("agent-a", ("agent-b",), report, 4)

        self.assertEqual(network._queue[0].valid_until_step, 7)

    def test_zero_latency_delivery_and_duplicate_rejection(self):
        network = NetworkSimulator(
            rng=random.Random(7),
            delivery_probability=1.0,
            max_latency_steps=0,
            duplicate_probability=1.0,
            partition_enabled=False,
            total_steps=10,
        )
        report = Observation("entity-1", 1.0, 2.0, 1, "agent-a")
        network.publish("agent-a", ("agent-b",), report, 1)
        seen = set()

        def receive(envelope: Envelope) -> str:
            if envelope.message_id in seen:
                return "duplicate"
            seen.add(envelope.message_id)
            return "queued"

        network.deliver_due(1, receive)
        self.assertEqual(network.sent_originals, 1)
        self.assertEqual(network.delivered_originals, 1)
        self.assertEqual(network.duplicate_copies_delivered, 1)
        self.assertEqual(network.duplicates_rejected, 1)
        self.assertEqual(network.pending_messages, 0)

    def test_zero_delivery_probability_drops_every_original(self):
        network = NetworkSimulator(
            rng=random.Random(1),
            delivery_probability=0.0,
            max_latency_steps=0,
            duplicate_probability=0.0,
            partition_enabled=False,
            total_steps=5,
        )
        report = Observation("entity-1", 1.0, 2.0, 1, "agent-a")
        network.publish("agent-a", ("agent-b",), report, 1)
        self.assertEqual(network.sent_originals, 1)
        self.assertEqual(network.dropped_originals, 1)
        self.assertEqual(network.pending_messages, 0)

    def test_partition_drops_message_at_delivery_and_reports_outage_state(self):
        class FixedLatencyRng:
            @staticmethod
            def random():
                return 0.0

            @staticmethod
            def randint(low, high):
                return high

        network = NetworkSimulator(
            rng=FixedLatencyRng(),
            delivery_probability=1.0,
            max_latency_steps=1,
            duplicate_probability=0.0,
            partition_enabled=True,
            total_steps=6,
        )
        report = Observation("entity-1", 1.0, 2.0, 1, "agent-a")
        received = []
        network.publish("agent-a", ("agent-b",), report, 1)

        self.assertEqual(network._queue[0].delivery_step, 2)
        self.assertEqual(network.communication_state(1), "available")
        self.assertEqual(network.communication_state(2), "partitioned")
        network.deliver_due(2, lambda envelope: received.append(envelope.message_id) or "queued")
        self.assertEqual(received, [])
        self.assertEqual(network.events[-1]["event_type"], "message_dropped")
        self.assertEqual(network.events[-1]["details"], "partition")
        self.assertEqual(network.communication_state(4), "available")


if __name__ == "__main__":
    unittest.main()
