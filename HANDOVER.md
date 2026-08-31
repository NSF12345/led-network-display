# Handover: LED Network Display poller

## What this is

A container that turns network interface traffic into a live particle
animation (cyan = RX, green = TX), rendered either to a browser preview
or a physical WS2812B LED strip via a WLED controller. Inspired by
https://adamslab.io/led-network-display.html.

Architecture: SNMP/dummy traffic source → particle renderer → one or
more output sinks (web/WebSocket, WLED/UDP). Sources and sinks are both
swappable behind small interfaces so none of them know about each other.

## Current state

Repo is scaffolded and committed locally (not yet pushed to a remote —
that's part of this handover). Built and reasoned through in a sandbox
with **no network access**, so testing was limited to what's possible
offline: Python syntax checks, and direct unit-style runs of the config
loader, dummy traffic source, and particle renderer (all confirmed
working — see commit history for what was checked). Nothing has been
run inside the actual Docker container, and `aiohttp`/`pysnmp` have
never been installed or imported successfully anywhere in this history.

## What's verified vs not

**Verified (actually run and checked):**
- `app/config.py` — env loading, conditional SNMP-field requirement based on `TRAFFIC_SOURCE`
- `app/renderer.py` — particle spawn/movement/fade logic, confirmed lit frames under synthetic load
- `app/dummy_traffic_source.py` — produces varied RX/TX samples including spikes, feeds renderer correctly
- All files pass `python3 -m py_compile`

**Not verified — do these first:**
1. `docker compose up -d --build` actually succeeds (Dockerfile has never been built)
2. `aiohttp` web server (`app/outputs/websocket_output.py`) actually serves the page and pushes WebSocket frames — never imported/run
3. If/when `TRAFFIC_SOURCE=snmp` is used: `app/snmp_poller.py` is written against `pysnmp-lextudio` 6.x's `pysnmp.hlapi.v3arch.asyncio` API from documentation/memory, never installed or run. Check `pip show pysnmp-lextudio` after install and watch first-poll logs closely — API shape may need adjusting for whatever version actually resolves. The SNMP mechanics (USM auth/priv setup, `ifHCInOctets`/`ifHCOutOctets` OIDs) should be correct regardless.
4. `app/outputs/wled_output.py` (DRGB UDP) — untestable until physical WLED hardware exists

## Immediate next steps

1. Build and run in dummy mode (default `.env.example` config) — confirms Docker/aiohttp/web page all work before touching anything SNMP-related
2. Push this repo to the user's GitHub org (currently local-only, two commits)
3. Once confirmed working, decide whether to keep iterating here or move to real SNMP mode against the user's UniFi switch (SNMPv3 — direct device polling, NOT the UniFi controller API, which only updates every ~10-40s via its inform protocol and is too coarse for this)

## Deployment target — user's homelab conventions

If/when this gets deployed to the user's actual infrastructure (not just dev-tested), it follows patterns established elsewhere in their homelab — worth reading their homelab skill/reference files if available in your environment, but key points:
- Stack management via **Dockge**, not raw `docker compose` on a host directly
- Secrets live in a per-stack `.env` file (gitignored), never inline in compose files or committed
- Before any compose rebuild on a stack with persistent data, check named volumes are `external: true` — not applicable here since this container has no persistent data/volumes, but worth knowing the convention
- Command hygiene the user expects: label every command read-only vs write/changes-something, pair actions with a verification command, one step at a time (don't chain unverified steps), investigate logs/state before proposing fixes

## Open decisions not yet made

- Physical LED strip length / final LED_COUNT (waiting on hardware purchase)
- Which specific switch port to monitor (SNMP_IF_INDEX) — needs `snmpwalk`-style discovery on the actual UniFi switch once SNMP is enabled on it
- Whether to run this via Dockge alongside the user's other stacks, or somewhere else — not yet decided
