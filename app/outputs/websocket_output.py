"""
Serves a static HTML/JS page that renders the LED strip as circles on a
canvas, and broadcasts each rendered frame to all connected browsers over
a WebSocket as JSON: {"frame": [r, g, b, r, g, b, ...], "rx": bytes_per_sec,
"tx": bytes_per_sec}.

This is the stand-in output sink for testing the animation before real
hardware exists - swap for WledOutput once you have a controller.
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
        # - empty for dummy mode, or if the lookup failed.
        self.device_info: dict = {}
        # Set by main.py only when TRAFFIC_SOURCE=dummy - lets the web UI's
        # inject buttons also force a temporary traffic rate override.
        self.traffic_source = None
        # Set by main.py - lets /api/inject trigger a particle burst
        # regardless of traffic source.
        self.renderer = None
        # Whether a manual inject burst should also reach the WLED strip
        # (not just the web preview). In-memory only, resets to False on
        # restart - not meant to persist.
        self.inject_to_led = False
        self._clients: set[web.WebSocketResponse] = set()
        self._app = web.Application()
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/api/info", self._handle_info)
        self._app.router.add_post("/api/inject", self._handle_inject)
        self._app.router.add_post("/api/inject-to-led", self._handle_inject_to_led)
        self._app.router.add_post("/api/effect", self._handle_effect)
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
                "sys_descr": self.device_info.get("sys_descr") or "",
                "snmp_version": self.cfg.SNMP_VERSION,
            }
        else:
            info = {"source": "dummy"}
        info["app_version"] = self.cfg.APP_VERSION
        return web.json_response(info)

    async def _handle_inject(self, request):
        try:
            body = await request.json()
            direction = body["direction"]
            if self.traffic_source is not None:
                self.traffic_source.inject(direction)
            if self.renderer is not None:
                self.renderer.inject(direction)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response({"ok": True})

    async def _handle_inject_to_led(self, request):
        try:
            body = await request.json()
            self.inject_to_led = bool(body["enabled"])
        except (json.JSONDecodeError, KeyError) as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response({"ok": True, "enabled": self.inject_to_led})

    async def _handle_effect(self, request):
        if self.renderer is not None:
            self.renderer.trigger_effect()
        return web.json_response({"ok": True})

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
