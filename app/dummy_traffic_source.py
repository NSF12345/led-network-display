"""
Generates synthetic RX/TX traffic samples on the same schedule and
callback interface as SnmpPoller.run(), so main.py can swap between
"dummy" and "snmp" sources via config.TRAFFIC_SOURCE without touching
the renderer or output sinks.

Traffic shape: a slowly wandering baseline (so it doesn't look perfectly
flat) plus occasional random bursts, independently for RX and TX. Not
meant to be realistic - just varied enough to exercise the full range
of the particle renderer (idle, moderate, heavy) while building/testing.
"""
import asyncio
import logging
import random
import time

from .traffic_rates import TrafficRates

log = logging.getLogger("dummy_traffic_source")


class DummyTrafficSource:
    def __init__(self, cfg):
        self.cfg = cfg
        self._rx_wander = 1.0  # multiplier on baseline, drifts over time
        self._tx_wander = 1.0

    def _next_sample(self) -> TrafficRates:
        # Slow random walk on the multiplier, clamped so it doesn't wander to zero or infinity.
        self._rx_wander = min(3.0, max(0.2, self._rx_wander + random.uniform(-0.1, 0.1)))
        self._tx_wander = min(3.0, max(0.2, self._tx_wander + random.uniform(-0.1, 0.1)))

        rx = self.cfg.DUMMY_RX_BASELINE_BYTES * self._rx_wander
        tx = self.cfg.DUMMY_TX_BASELINE_BYTES * self._tx_wander

        if random.random() < self.cfg.DUMMY_SPIKE_CHANCE:
            rx += random.uniform(0, self.cfg.DUMMY_SPIKE_MAX_BYTES)
        if random.random() < self.cfg.DUMMY_SPIKE_CHANCE:
            tx += random.uniform(0, self.cfg.DUMMY_SPIKE_MAX_BYTES)

        return TrafficRates(rx_bytes_per_sec=rx, tx_bytes_per_sec=tx)

    async def run(self, on_sample):
        """Matches SnmpPoller.run()'s signature: calls on_sample(TrafficRates) once per POLL_INTERVAL_SECONDS."""
        interval = self.cfg.POLL_INTERVAL_SECONDS
        log.info("Dummy traffic source running (no real SNMP target)")
        while True:
            start = time.monotonic()
            on_sample(self._next_sample())
            elapsed = time.monotonic() - start
            await asyncio.sleep(max(0.0, interval - elapsed))
