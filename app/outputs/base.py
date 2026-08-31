"""
Common interface for anywhere a rendered frame can go. This is the seam
that lets the same renderer feed a browser now and a physical WLED strip
later without touching snmp_poller.py or renderer.py.
"""
from abc import ABC, abstractmethod


class OutputSink(ABC):
    @abstractmethod
    async def send_frame(self, frame: list[tuple[int, int, int]]) -> None:
        """frame is a list of (r, g, b) 0-255 tuples, one per LED, in order."""
        raise NotImplementedError

    async def start(self) -> None:
        """Optional: override for sinks that need setup (e.g. opening a server)."""
        pass

    async def stop(self) -> None:
        """Optional: override for sinks that need teardown."""
        pass
