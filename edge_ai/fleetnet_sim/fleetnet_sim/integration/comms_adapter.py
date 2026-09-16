"""Communication backend selection + a telemetry-logging wrapper.

The wrapper never changes dispatch semantics — it only observes
``publish`` calls (before delegating to the real bus) and reports a
``communication_events``-shaped dict (Section 17) to a callback. Default
backend is ``InProcessBus`` (fast, synchronous, good for large batch ML
data-generation sweeps); ``ZenohBus`` is available via config for
realism/latency-focused runs, using the exact real implementation
(``core/comms/zenoh_bus.py``) validated by
``Fleet_SIH/tests/validation/test_zenoh_validation.py``.
"""
from __future__ import annotations

import pickle
import time
import uuid
from typing import Any, Callable, Optional

from core.comms.bus import Handler, MessageBus
from core.comms.inprocess import InProcessBus

from fleetnet_sim.config.schema import CommsBackend, CommunicationConfig

CommEventSink = Callable[[dict], None]


class LoggingBus(MessageBus):
    def __init__(self, inner: MessageBus, get_sim_time: Callable[[], float], sink: Optional[CommEventSink] = None):
        self._inner = inner
        self._get_sim_time = get_sim_time
        self._sink = sink

    def publish(self, topic: str, payload: Any) -> None:
        if self._sink is not None:
            try:
                size = len(pickle.dumps(payload))
            except Exception:
                size = -1
            self._sink(
                {
                    "message_id": str(uuid.uuid4()),
                    "topic": topic,
                    "source": topic.split("/")[1] if topic.startswith("fleet/") else None,
                    "message_type": topic.rsplit("/", 1)[-1],
                    "simulation_time": self._get_sim_time(),
                    "payload_size_bytes": size,
                    "wall_time": time.monotonic(),
                }
            )
        self._inner.publish(topic, payload)

    def subscribe(self, pattern: str, handler: Handler) -> None:
        self._inner.subscribe(pattern, handler)

    def message_count(self) -> int:
        return self._inner.message_count()


def make_bus(config: CommunicationConfig, get_sim_time: Callable[[], float], sink: Optional[CommEventSink] = None) -> MessageBus:
    if config.backend == CommsBackend.ZENOH:
        from core.comms.zenoh_bus import ZenohBus

        inner: MessageBus = ZenohBus(inject_delay_s=config.inject_delay_s, inject_loss_rate=config.inject_loss_rate)
    else:
        inner = InProcessBus()
    return LoggingBus(inner, get_sim_time, sink)
