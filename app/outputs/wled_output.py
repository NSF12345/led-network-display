"""
Pushes frames to a real WLED controller using its realtime UDP protocol
(DRGB). Not wired in by default (WLED_ENABLED=false) - flip on once you
have hardware, in parallel with or instead of the web output.

DRGB packet format (WLED realtime UDP docs):
  byte 0:      protocol id, 2 = DRGB
  byte 1:      timeout in seconds - if WLED doesn't receive another
               packet within this window, it reverts to its last preset.
               This is the fallback behavior described in the blog post:
               kill this process and the strip won't freeze/go dark.
  bytes 2..N:  3 bytes (R,G,B) per LED, in strip order.

UDP is fire-and-forget - no ack, no retry. That's fine here: a dropped
frame just gets superseded by the next one a fraction of a second later.
"""
import asyncio
import logging

from .base import OutputSink

log = logging.getLogger("wled_output")

DRGB_PROTOCOL_ID = 2


class WledOutput(OutputSink):
    def __init__(self, cfg):
        self.cfg = cfg
        self._transport = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        # Connected UDP socket - just lets us use transport.sendto without
        # re-specifying the address each call; UDP itself stays connectionless.
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: asyncio.DatagramProtocol(),
            remote_addr=(self.cfg.WLED_HOST, self.cfg.WLED_PORT),
        )
        log.info("WLED UDP output targeting %s:%d", self.cfg.WLED_HOST, self.cfg.WLED_PORT)

    async def stop(self) -> None:
        if self._transport:
            self._transport.close()

    async def send_frame(self, frame: list[tuple[int, int, int]], rx_rate: float, tx_rate: float) -> None:
        if not self._transport:
            return
        packet = bytearray()
        packet.append(DRGB_PROTOCOL_ID)
        packet.append(self.cfg.WLED_TIMEOUT_SECONDS)
        for r, g, b in frame:
            packet.extend((r, g, b))
        self._transport.sendto(bytes(packet))
