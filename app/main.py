"""
Entrypoint. Runs three concurrent loops:
  1. SNMP poller - updates the renderer's current RX/TX rates once per POLL_INTERVAL_SECONDS
  2. Render loop - steps the particle simulation and pushes frames to every
     enabled output sink at RENDER_FPS
  3. Each output sink's own server (currently just the web sink's HTTP server)
"""
import asyncio
import logging
import time

from .config import config
from .outputs import WebsocketOutput, WledOutput
from .renderer import ParticleRenderer

logging.basicConfig(level=config.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")


def build_traffic_source():
    """Import pysnmp only if actually needed - dummy mode should never
    require it to be installed correctly."""
    if config.TRAFFIC_SOURCE == "snmp":
        from .snmp_poller import SnmpPoller
        return SnmpPoller(config)
    elif config.TRAFFIC_SOURCE == "dummy":
        from .dummy_traffic_source import DummyTrafficSource
        return DummyTrafficSource(config)
    else:
        raise RuntimeError(f"Unknown TRAFFIC_SOURCE: {config.TRAFFIC_SOURCE!r} (expected 'dummy' or 'snmp')")


async def render_loop(renderer: ParticleRenderer, sinks: list, last_sample_time: list):
    frame_interval = 1.0 / config.RENDER_FPS
    last = time.monotonic()
    stale_logged = False
    while True:
        now = time.monotonic()
        dt = now - last
        last = now

        if now - last_sample_time[0] > config.STALE_DATA_TIMEOUT_SECONDS:
            # No fresh traffic sample recently (e.g. SNMP target unreachable) -
            # decay to idle instead of looping the last-known rates forever.
            renderer.update_rates(0.0, 0.0)
            if not stale_logged:
                log.warning("No traffic sample in over %.0fs - fading to idle", config.STALE_DATA_TIMEOUT_SECONDS)
                stale_logged = True
        else:
            stale_logged = False

        frame = renderer.step(dt)
        for sink in sinks:
            try:
                await sink.send_frame(frame, renderer.rx_rate, renderer.tx_rate)
            except Exception:
                log.exception("Output sink %s failed to send frame", sink)

        elapsed = time.monotonic() - now
        await asyncio.sleep(max(0.0, frame_interval - elapsed))


async def main():
    renderer = ParticleRenderer(config)
    poller = build_traffic_source()

    sinks = []
    web_sink = None
    if config.WEB_ENABLED:
        web_sink = WebsocketOutput(config)
        sinks.append(web_sink)
    if config.WLED_ENABLED:
        sinks.append(WledOutput(config))

    if not sinks:
        log.warning("No output sinks enabled (WEB_ENABLED and WLED_ENABLED both false) - nothing will be visible")

    if web_sink is not None and config.TRAFFIC_SOURCE == "snmp":
        # Best-effort, one-off lookup so the web preview can show which
        # switch/port it's actually polling instead of just the raw IP.
        web_sink.device_info = await poller.get_device_info()

    for sink in sinks:
        await sink.start()

    last_sample_time = [time.monotonic()]

    def on_sample(rates):
        # DEBUG, not INFO - this fires once per POLL_INTERVAL_SECONDS
        # forever, and the web preview already shows live rates in the UI.
        log.debug("RX %.0f B/s  TX %.0f B/s", rates.rx_bytes_per_sec, rates.tx_bytes_per_sec)
        renderer.update_rates(rates.rx_bytes_per_sec, rates.tx_bytes_per_sec)
        last_sample_time[0] = time.monotonic()

    try:
        await asyncio.gather(
            poller.run(on_sample),
            render_loop(renderer, sinks, last_sample_time),
        )
    finally:
        for sink in sinks:
            await sink.stop()


if __name__ == "__main__":
    asyncio.run(main())
