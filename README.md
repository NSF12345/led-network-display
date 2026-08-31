# LED Network Display — poller

Polls a switch interface over SNMPv3, turns RX/TX byte rates into a
moving-particle animation, and renders it. Two output sinks, either or
both can be enabled:

- **Web** — serves a browser page (canvas) showing the strip live over
  WebSocket. This is the one to use before you have hardware.
- **WLED** — pushes frames to a real WLED controller via its realtime
  UDP protocol (DRGB). Disabled by default; flip on in `.env` once you
  have a controller on the network.

Both can run simultaneously — useful for confirming the physical strip
matches what the browser shows while tuning colors/speed.

## Status / what's untested

The SNMP client code (`app/snmp_poller.py`) is written against
`pysnmp-lextudio` 6.x's `pysnmp.hlapi.v3arch.asyncio` API but **has not
been run against a live device** — no network access in the environment
this was built in. Before relying on it:

1. `pip show pysnmp-lextudio` after install, confirm version ~6.1.x
2. Run the container and check logs for the first poll cycle — either
   real RX/TX numbers, or a clear SNMP error (auth failure, wrong
   ifIndex, etc.) rather than a silent hang
3. If pysnmp throws an import/API error, the SNMP mechanics (USM
   auth/priv setup, `ifHCInOctets`/`ifHCOutOctets` OIDs against your
   `SNMP_IF_INDEX`) are still correct — only the exact call shape might
   need adjusting for your installed version

Everything else (renderer, both output sinks, web page) has no external
dependencies and should work as-is.

## Setup

```
cp .env.example .env
```

Edit `.env`:
- `SNMP_HOST` / `SNMP_IF_INDEX` — your switch and the port you want reflected
- `SNMP_USER` / `SNMP_AUTH_PASSWORD` / `SNMP_PRIV_PASSWORD` — your v3 credentials
- `SNMP_AUTH_PROTOCOL` / `SNMP_PRIV_PROTOCOL` — must match what's configured on the switch (common: SHA + AES128)
- `LED_COUNT` — set to your actual strip length once known; safe to leave at default for now, since the web preview scales to whatever count you give it

## Run

```
docker compose up -d --build
```
**Write action** — builds the image and starts the container.

Check it started and see the first poll cycle:
```
docker compose logs -f led-network-poller
```
**Read-only.** Look for `RX ... B/s  TX ... B/s` lines once per
`POLL_INTERVAL_SECONDS`. An `SNMP poll failed` traceback here means
check credentials/ifIndex/reachability, not a code bug.

Then open `http://<host>:8080` in a browser — you should see particles
moving across a row of dots whenever there's real traffic on the
monitored interface.

## Tuning

All in `.env`, no code changes needed:
- `RATE_SCALE_MIN_BYTES` / `RATE_SCALE_MAX_BYTES` — sets what counts as
  "idle" vs "maxed out" for the log-scaled brightness/spawn-rate mapping.
  Adjust to your actual link's typical traffic range.
- `PARTICLE_SPEED_PIXELS_PER_SEC` / `PARTICLE_TRAIL_LENGTH` — animation feel
- `RX_COLOR` / `TX_COLOR` — comma-separated R,G,B

## Moving to real hardware

Once you have a WLED controller on the network:
1. Set `WLED_ENABLED=true`, `WLED_HOST=<controller ip>` in `.env`
2. `docker compose up -d` to pick up the env change — **write action**,
   recreates the container
3. Confirm frames arriving: WLED's UI should show "Live" / realtime mode
   active while the container runs, and revert to its normal preset
   within `WLED_TIMEOUT_SECONDS` if you stop the container — verify that
   fallback explicitly rather than assuming it works
