"""
Common interface for anywhere a rendered frame can go. This is the seam
that lets the same renderer feed a browser now and a physical WLED strip
later without touching snmp_poller.py or renderer.py.
"""
from abc import ABC, abstractmethod


class OutputSink(ABC):
    @abstractmethod
    async def send_frame(self, frame: list[tuple[int, int, int]], rx_rate: float, tx_rate: float) -> None:
        """frame is a list of (r, g, b) 0-255 tuples, one per LED, in order.
        rx_rate/tx_rate are the current smoothed bytes/sec, for sinks that
        want to display them (e.g. the web preview's legend) — sinks that
        only care about pixels (e.g. WLED) can ignore them."""
        raise NotImplementedError

    async def start(self) -> None:
        """Optional: override for sinks that need setup (e.g. opening a server)."""
        pass

    async def stop(self) -> None:
        """Optional: override for sinks that need teardown."""
        pass
