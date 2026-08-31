"""
Entrypoint. Runs three concurrent loops:
  1. SNMP poller — updates the renderer's current RX/TX rates once per POLL_INTERVAL_SECONDS
  2. Render loop — steps the particle simulation and pushes frames to every
     enabled output sink at RENDER_FPS
  3. Each output sink's own server (currently just the web sink's HTTP server)
"""
import asyncio
import logging
import time

from .config import config
from .outputs import WebsocketOutput, WledOutput
from .renderer import ParticleRenderer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")


def build_traffic_source():
    """Import pysnmp only if actually needed — dummy mode should never
    require it to be installed correctly."""
    if config.TRAFFIC_SOURCE == "snmp":
        from .snmp_poller import SnmpPoller
        return SnmpPoller(config)
    elif config.TRAFFIC_SOURCE == "dummy":
        from .dummy_traffic_source import DummyTrafficSource
        return DummyTrafficSource(config)
    else:
        raise RuntimeError(f"Unknown TRAFFIC_SOURCE: {config.TRAFFIC_SOURCE!r} (expected 'dummy' or 'snmp')")


async def render_loop(renderer: ParticleRenderer, sinks: list):
    frame_interval = 1.0 / config.RENDER_FPS
    last = time.monotonic()
    while True:
        now = time.monotonic()
        dt = now - last
        last = now

        frame = renderer.step(dt)
        for sink in sinks:
            try:
                await sink.send_frame(frame)
            except Exception:
                log.exception("Output sink %s failed to send frame", sink)

        elapsed = time.monotonic() - now
        await asyncio.sleep(max(0.0, frame_interval - elapsed))


async def main():
    renderer = ParticleRenderer(config)
    poller = build_traffic_source()

    sinks = []
    if config.WEB_ENABLED:
        sinks.append(WebsocketOutput(config))
    if config.WLED_ENABLED:
        sinks.append(WledOutput(config))

    if not sinks:
        log.warning("No output sinks enabled (WEB_ENABLED and WLED_ENABLED both false) — nothing will be visible")

    for sink in sinks:
        await sink.start()

    def on_sample(rates):
        log.info("RX %.0f B/s  TX %.0f B/s", rates.rx_bytes_per_sec, rates.tx_bytes_per_sec)
        renderer.update_rates(rates.rx_bytes_per_sec, rates.tx_bytes_per_sec)

    try:
        await asyncio.gather(
            poller.run(on_sample),
            render_loop(renderer, sinks),
        )
    finally:
        for sink in sinks:
            await sink.stop()


if __name__ == "__main__":
    asyncio.run(main())
