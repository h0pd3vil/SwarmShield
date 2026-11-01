"""In-process publish/subscribe network with deterministic fault simulation."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Callable, Mapping

from .observations import Observation


MESSAGE_PROTOCOL_VERSION = 1


@dataclass(frozen=True)
class Envelope:
    message_id: str
    sender_id: str
    recipient_id: str
    observation: Observation
    sent_step: int
    delivery_step: int
    copy_index: int = 0
    message_type: str = "observation"
    protocol_version: int = MESSAGE_PROTOCOL_VERSION
    valid_until_step: int | None = None
    attempt: int = 0

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value for value in (
            self.message_id,
            self.sender_id,
            self.recipient_id,
        )):
            raise ValueError("message ID, sender, and recipient must be non-empty")
        if not isinstance(self.message_type, str) or not self.message_type:
            raise ValueError("message_type must be a non-empty string")
        if type(self.protocol_version) is not int or self.protocol_version < 1:
            raise ValueError("protocol_version must be a positive integer")
        if type(self.sent_step) is not int or type(self.delivery_step) is not int:
            raise ValueError("message ticks must be integers")
        if self.sent_step < 0 or self.delivery_step < self.sent_step:
            raise ValueError("message ticks must be non-negative and delivery cannot precede creation")
        if type(self.copy_index) is not int or self.copy_index not in (0, 1):
            raise ValueError("copy_index must be 0 or 1")
        if self.valid_until_step is not None and type(self.valid_until_step) is not int:
            raise ValueError("valid_until_step must be an integer or null")
        if self.valid_until_step is not None and self.valid_until_step < self.sent_step:
            raise ValueError("valid_until_step cannot precede message creation")
        if type(self.attempt) is not int or self.attempt < 0:
            raise ValueError("attempt must be a non-negative integer")
        if not isinstance(self.observation, Observation):
            raise ValueError("observation message payload must be an Observation")

    @property
    def created_step(self) -> int:
        """The tick at which this message envelope was created and sent."""
        return self.sent_step

    @property
    def provenance(self) -> dict[str, object]:
        return {
            "source_agent_id": self.observation.source_agent_id,
            "observed_at": self.observation.observed_at,
        }

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "entity_id": self.observation.entity_id,
            "x": self.observation.x,
            "y": self.observation.y,
            "observed_at": self.observation.observed_at,
            "source_agent_id": self.observation.source_agent_id,
            "confidence": self.observation.confidence,
        }
        if self.observation.sensor_coverage_cells:
            payload["sensor_coverage_cells"] = [
                [column, row]
                for column, row in self.observation.sensor_coverage_cells
            ]
        return {
            "protocol_version": self.protocol_version,
            "message_id": self.message_id,
            "message_type": self.message_type,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "created_step": self.created_step,
            "delivery_step": self.delivery_step,
            "valid_until_step": self.valid_until_step,
            "copy_index": self.copy_index,
            "attempt": self.attempt,
            "provenance": self.provenance,
            "payload": payload,
        }


class NetworkSimulator:
    def __init__(
        self,
        rng: random.Random,
        delivery_probability: float,
        max_latency_steps: int,
        duplicate_probability: float,
        partition_enabled: bool,
        total_steps: int,
        communication_range: float | None = None,
        queue_capacity: int = 10000,
        message_ttl_steps: int | None = None,
        max_retries: int = 0,
    ) -> None:
        if communication_range is not None and (
            isinstance(communication_range, bool)
            or not isinstance(communication_range, (int, float))
            or not math.isfinite(communication_range)
            or communication_range <= 0.0
        ):
            raise ValueError("communication_range must be finite and greater than zero or null")
        if type(queue_capacity) is not int or queue_capacity <= 0:
            raise ValueError("queue_capacity must be greater than zero")
        if message_ttl_steps is not None and (
            type(message_ttl_steps) is not int or message_ttl_steps < 0
        ):
            raise ValueError("message_ttl_steps cannot be negative")
        if type(max_retries) is not int or max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self._rng = rng
        self._delivery_probability = delivery_probability
        self._max_latency_steps = max_latency_steps
        self._duplicate_probability = duplicate_probability
        self._partition_enabled = partition_enabled
        self._communication_range = communication_range
        self._queue_capacity = queue_capacity
        self._message_ttl_steps = message_ttl_steps
        self._max_retries = max_retries
        self._partition_start = total_steps // 3
        self._partition_end = max(self._partition_start + 1, (2 * total_steps) // 3)
        self._queue: list[Envelope] = []
        self._next_message_number = 1
        self.events: list[dict[str, object]] = []
        self.sent_originals = 0
        self.delivered_originals = 0
        self.dropped_originals = 0
        self.duplicate_copies_scheduled = 0
        self.duplicate_copies_delivered = 0
        self.dropped_duplicate_copies = 0
        self.duplicates_rejected = 0
        self.delivered_latencies: list[int] = []
        self.message_retries = 0
        self.expired_originals = 0
        self.expired_duplicate_copies = 0

    def publish(
        self,
        sender_id: str,
        recipient_ids: tuple[str, ...],
        observation: Observation,
        step: int,
        *,
        valid_until_step: int | None = None,
        sender_position: tuple[float, float] | None = None,
        recipient_positions: Mapping[str, tuple[float, float]] | None = None,
    ) -> None:
        if type(step) is not int or step < 0:
            raise ValueError("message creation step must be a non-negative integer")
        if valid_until_step is not None and type(valid_until_step) is not int:
            raise ValueError("valid_until_step must be an integer or null")
        if valid_until_step is not None and valid_until_step < step:
            raise ValueError("valid_until_step cannot precede message creation")
        for recipient_id in recipient_ids:
            message_id = f"msg-{self._next_message_number:08d}"
            self._next_message_number += 1
            self.sent_originals += 1
            self._record(
                step,
                "message_sent",
                message_id,
                sender_id,
                recipient_id,
                observation.entity_id,
            )

            if self._in_partition(step):
                self.dropped_originals += 1
                self._record(step, "message_dropped", message_id, sender_id, recipient_id, observation.entity_id, "partition")
                continue
            recipient_position = recipient_positions.get(recipient_id) if recipient_positions is not None else None
            if self._communication_range is not None:
                if sender_position is None or recipient_position is None:
                    self.dropped_originals += 1
                    self._record(
                        step, "message_dropped", message_id, sender_id, recipient_id,
                        observation.entity_id, "endpoint_position_unavailable",
                    )
                    continue
                if math.dist(sender_position, recipient_position) > self._communication_range:
                    self.dropped_originals += 1
                    self._record(
                        step, "message_dropped", message_id, sender_id, recipient_id,
                        observation.entity_id, "out_of_range",
                    )
                    continue
            if len(self._queue) >= self._queue_capacity:
                self.dropped_originals += 1
                self._record(
                    step, "message_dropped", message_id, sender_id, recipient_id,
                    observation.entity_id, "queue_capacity",
                )
                continue

            expiry = valid_until_step
            if expiry is None and self._message_ttl_steps is not None:
                expiry = step + self._message_ttl_steps
            for attempt in range(self._max_retries + 1):
                if self._rng.random() >= self._delivery_probability:
                    if attempt < self._max_retries:
                        self.message_retries += 1
                        self._record(
                            step,
                            "message_retry_attempted",
                            message_id,
                            sender_id,
                            recipient_id,
                            observation.entity_id,
                            f"attempt={attempt + 1};reason=loss",
                        )
                        continue
                    self.dropped_originals += 1
                    self._record(step, "message_dropped", message_id, sender_id, recipient_id, observation.entity_id, "loss")
                    break

                latency = self._rng.randint(0, self._max_latency_steps)
                self._queue.append(
                    Envelope(
                        message_id,
                        sender_id,
                        recipient_id,
                        observation,
                        step,
                        step + latency,
                        valid_until_step=expiry,
                        attempt=attempt,
                    )
                )
                if self._rng.random() < self._duplicate_probability:
                    if len(self._queue) < self._queue_capacity:
                        self.duplicate_copies_scheduled += 1
                        self._queue.append(
                            Envelope(
                                message_id,
                                sender_id,
                                recipient_id,
                                observation,
                                step,
                                step + latency,
                                1,
                                valid_until_step=expiry,
                                attempt=attempt,
                            )
                        )
                        self._record(step, "duplicate_scheduled", message_id, sender_id, recipient_id, observation.entity_id)
                    else:
                        self.dropped_duplicate_copies += 1
                        self._record(
                            step, "message_dropped", message_id, sender_id, recipient_id,
                            observation.entity_id, "queue_capacity", 1,
                        )
                break

    def deliver_due(self, step: int, receiver: Callable[[Envelope], str]) -> None:
        due = [
            envelope for envelope in self._queue
            if envelope.delivery_step <= step
            or (envelope.valid_until_step is not None and envelope.valid_until_step < step)
        ]
        due_ids = {id(envelope) for envelope in due}
        self._queue = [envelope for envelope in self._queue if id(envelope) not in due_ids]
        due.sort(key=lambda envelope: (envelope.delivery_step, envelope.message_id, envelope.copy_index))

        for envelope in due:
            if envelope.valid_until_step is not None and step > envelope.valid_until_step:
                if envelope.copy_index == 0:
                    self.expired_originals += 1
                else:
                    self.expired_duplicate_copies += 1
                self._record(
                    step,
                    "message_expired",
                    envelope.message_id,
                    envelope.sender_id,
                    envelope.recipient_id,
                    envelope.observation.entity_id,
                    f"valid_until_step={envelope.valid_until_step}",
                    envelope.copy_index,
                )
                continue
            if self._in_partition(step):
                if envelope.copy_index == 0:
                    self.dropped_originals += 1
                else:
                    self.dropped_duplicate_copies += 1
                self._record(
                    step,
                    "message_dropped",
                    envelope.message_id,
                    envelope.sender_id,
                    envelope.recipient_id,
                    envelope.observation.entity_id,
                    "partition",
                    envelope.copy_index,
                )
                continue

            outcome = receiver(envelope)
            if envelope.copy_index == 0:
                self.delivered_originals += 1
                self.delivered_latencies.append(step - envelope.sent_step)
                self._record(
                    step,
                    "message_delivered",
                    envelope.message_id,
                    envelope.sender_id,
                    envelope.recipient_id,
                    envelope.observation.entity_id,
                    outcome,
                )
            else:
                self.duplicate_copies_delivered += 1
                if outcome == "duplicate":
                    self.duplicates_rejected += 1
                self._record(
                    step,
                    "duplicate_delivered",
                    envelope.message_id,
                    envelope.sender_id,
                    envelope.recipient_id,
                    envelope.observation.entity_id,
                    outcome,
                    envelope.copy_index,
                )

    @property
    def pending_messages(self) -> int:
        return len(self._queue)

    def record_pending(self, step: int) -> None:
        for envelope in sorted(
            self._queue,
            key=lambda queued: (queued.delivery_step, queued.message_id, queued.copy_index),
        ):
            self._record(
                step,
                "message_pending",
                envelope.message_id,
                envelope.sender_id,
                envelope.recipient_id,
                envelope.observation.entity_id,
                f"scheduled_for_step={envelope.delivery_step}",
                envelope.copy_index,
            )

    @property
    def pending_original_messages(self) -> int:
        return sum(envelope.copy_index == 0 for envelope in self._queue)

    @property
    def pending_duplicate_copies(self) -> int:
        return sum(envelope.copy_index != 0 for envelope in self._queue)

    def communication_state(self, step: int) -> str:
        """Report the configured global simulated network availability at a tick."""
        if not self._partition_enabled:
            return "available"
        return "partitioned" if self._in_partition(step) else "available"

    def _in_partition(self, step: int) -> bool:
        return (
            self._partition_enabled
            and self._partition_start <= step < self._partition_end
        )

    def _record(
        self,
        step: int,
        event_type: str,
        message_id: str,
        sender_id: str,
        recipient_id: str,
        entity_id: str,
        details: str = "",
        copy_index: int = 0,
    ) -> None:
        self.events.append(
            {
                "step": step,
                "event_type": event_type,
                "message_id": message_id,
                "sender_id": sender_id,
                "recipient_id": recipient_id,
                "entity_id": entity_id,
                "details": details,
                "copy_index": copy_index,
            }
        )
