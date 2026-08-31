"""
Serves a static HTML/JS page that renders the LED strip as circles on a
canvas, and broadcasts each rendered frame to all connected browsers over
a WebSocket as JSON: {"frame": [r, g, b, r, g, b, ...], "rx": bytes_per_sec,
"tx": bytes_per_sec}.

This is the stand-in output sink for testing the animation before real
hardware exists — swap for WledOutput once you have a controller.
"""
import json
import logging
from pathlib import Path

from aiohttp import web, WSMsgType

from .base import OutputSink

log = logging.getLogger("websocket_output")

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"


class WebsocketOutput(OutputSink):
    def __init__(self, cfg):
        self.cfg = cfg
        # Set by main.py after a one-off SNMP lookup (switch_name, switch_port)
        # — empty for dummy mode, or if the lookup failed.
        self.device_info: dict = {}
        self._clients: set[web.WebSocketResponse] = set()
        self._app = web.Application()
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/api/info", self._handle_info)
        self._app.router.add_get("/ws", self._handle_ws)
        self._app.router.add_static("/static/", WEB_DIR, name="static")
        self._runner = None

    async def _handle_index(self, request):
        return web.FileResponse(WEB_DIR / "index.html")

    async def _handle_info(self, request):
        if self.cfg.TRAFFIC_SOURCE == "snmp":
            info = {
                "source": "snmp",
                "host": self.cfg.SNMP_HOST,
                "switch_name": self.device_info.get("switch_name") or self.cfg.SNMP_HOST,
                "switch_port": self.device_info.get("switch_port") or f"ifIndex {self.cfg.SNMP_IF_INDEX}",
            }
        else:
            info = {"source": "dummy"}
        return web.json_response(info)

    async def _handle_ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)
        log.info("Browser connected (%d total)", len(self._clients))
        try:
            async for msg in ws:
                if msg.type == WSMsgType.ERROR:
                    log.warning("WebSocket error: %s", ws.exception())
        finally:
            self._clients.discard(ws)
            log.info("Browser disconnected (%d total)", len(self._clients))
        return ws

    async def start(self) -> None:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.cfg.WEB_HOST, self.cfg.WEB_PORT)
        await site.start()
        log.info("Web visualization listening on http://%s:%d", self.cfg.WEB_HOST, self.cfg.WEB_PORT)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    async def send_frame(self, frame: list[tuple[int, int, int]], rx_rate: float, tx_rate: float) -> None:
        if not self._clients:
            return
        flat = [v for rgb in frame for v in rgb]
        payload = json.dumps({"frame": flat, "rx": rx_rate, "tx": tx_rate})
        dead = []
        for ws in self._clients:
            try:
                await ws.send_str(payload)
            except ConnectionResetError:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)
