# Testing a new SNMP device (for an AI agent)

This is a runbook, not a log - follow it fresh each time rather than reading it as history. It exists because this project's SNMP support was built and validated by an AI agent (Claude) across several real UniFi devices, and this captures what actually worked so the next session doesn't have to rediscover it.

Ask the user for the device's IP, and its SNMP credentials (community string for v1/v2c, or username+auth/priv passwords for v3) before starting - don't guess or reuse another device's credentials.

## 0. Environment note

This project depends on `pysnmp-lextudio`. The API shape that actually works (verified against 6.3.0) is `pysnmp.hlapi.asyncio` - **not** `pysnmp.hlapi.v3arch.asyncio`, which is what older docs/training data may suggest. `getCmd`/`nextCmd` (camelCase), not `get_cmd`. `UdpTransportTarget(...)` is a plain sync constructor, not an async factory. If none of that matches what's installed, check `pip show pysnmp-lextudio` and inspect the actual package (`python -c "import pysnmp.hlapi.asyncio as a; print(dir(a))"`) rather than trusting assumptions - this API has moved across versions before.

Symbolic MIB names (`ObjectIdentity("IF-MIB", "ifHCInOctets", idx)`) throw `MibNotFoundError` - this package doesn't bundle the IF-MIB module. Use raw numeric OIDs instead (all listed below).

## 1. Confirm reachability/auth

Cheapest possible check - `sysName`/`sysDescr`, not traffic counters yet:

```python
import asyncio
from pysnmp.hlapi.asyncio import (
    CommunityData, ContextData, ObjectIdentity, ObjectType, SnmpEngine,
    UdpTransportTarget, getCmd,
)
# for v3: from pysnmp.hlapi.asyncio import UsmUserData, usmHMACSHAAuthProtocol, usmAesCfb128Protocol

async def main():
    engine = SnmpEngine()
    auth = CommunityData('COMMUNITY_STRING', mpModel=1)  # mpModel=1 is v2c, 0 is v1
    # v3 instead: auth = UsmUserData('user', authKey='authpass', privKey='privpass',
    #                                 authProtocol=usmHMACSHAAuthProtocol, privProtocol=usmAesCfb128Protocol)
    transport = UdpTransportTarget(('DEVICE_IP', 161), timeout=3, retries=1)
    context = ContextData()
    errInd, errStat, errIdx, varBinds = await getCmd(
        engine, auth, transport, context,
        ObjectType(ObjectIdentity('1.3.6.1.2.1.1.5.0')),  # sysName
        ObjectType(ObjectIdentity('1.3.6.1.2.1.1.1.0')),  # sysDescr
    )
    print(errInd, errStat, [str(v) for _, v in varBinds] if not errInd else None)

asyncio.run(main())
```

SNMP doesn't distinguish "wrong credentials" from "wrong IP/unreachable" - both just time out with no error detail. If this fails, verify basic connectivity (ping) and that SNMP is actually enabled on the device before assuming the credentials are wrong.

## 2. Find the real `ifIndex` - do not assume 1

Walk `ifDescr` (`1.3.6.1.2.1.2.2.1.2`) and/or `ifName` (`1.3.6.1.2.1.31.1.1.1.1`):

```python
async def walk(host, auth, oid_base):
    engine = SnmpEngine()
    transport = UdpTransportTarget((host, 161), timeout=3, retries=1)
    context = ContextData()
    current = ObjectType(ObjectIdentity(oid_base))
    for _ in range(40):
        errInd, errStat, errIdx, varBinds = await nextCmd(engine, auth, transport, context, current)
        if errInd or int(errStat) != 0 or not varBinds:
            break
        name, val = varBinds[0][0]
        if not str(name).startswith(oid_base + '.'):
            break
        print(str(name), '=', val.prettyPrint())
        current = ObjectType(ObjectIdentity(name))
```
(needs `nextCmd` imported alongside `getCmd`)

**Watch for `lo` (loopback) at index 1** on anything Linux-based (gateways, APs almost always have this - plain switches usually don't). If you skip this step and just query index 1 blindly, the tell is that RX and TX come back as the *exact same number* - essentially impossible for real traffic, but exactly what loopback always does since it mirrors everything it sends back to itself.

Some devices (APs especially) list a dozen-plus interfaces - loopback, radios, per-SSID VAPs, VLAN sub-interfaces, bridges, tunnels - not just "the one real port." Prefer the physical wired uplink (an `eth0`-style entry) over wifi/VAP/bridge/VLAN sub-interfaces, unless you specifically want a sub-interface's traffic instead of the device's overall link.

## 3. Verify real traffic, not a fluke

A single counter read proves nothing. Pull the same OID twice, a couple of seconds apart, confirm the value actually increased:

```python
in_oid, out_oid = '1.3.6.1.2.1.31.1.1.1.6', '1.3.6.1.2.1.31.1.1.1.10'  # ifHCInOctets/ifHCOutOctets (v2c/v3)
# v1 only: '1.3.6.1.2.1.2.2.1.10' / '1.3.6.1.2.1.2.2.1.16' (32-bit ifInOctets/ifOutOctets instead - v1 can't carry Counter64)
```
Query `{in_oid}.{ifIndex}` and `{out_oid}.{ifIndex}` via `getCmd`, sleep 2-3s, query again. A single `0` delta isn't necessarily broken (genuine idle moment) - sample a few times before concluding either way.

## 4. Run it through the actual app

Don't stop at raw queries - they don't prove the app's own code path works. Set `.env` (`TRAFFIC_SOURCE=snmp`, `SNMP_HOST`, `SNMP_IF_INDEX`, `SNMP_VERSION`, and that version's credential block), run `python -m app.main` locally (`.env` isn't auto-loaded outside Docker - `set -a; source .env; set +a` first), then:

If the port bind fails, a stale process from an earlier test run may already be squatting on 8080 - check `netstat`/`lsof` for it and kill it before assuming something's actually broken.
- `curl localhost:8080/api/info` - should show real `switch_name`/`switch_port`/`sys_descr` for this device, not an error
- watch the log for a couple of poll cycles (`LOG_LEVEL=DEBUG` to see the per-poll RX/TX line) - confirm rates are nonzero/plausible, not stuck at 0 forever
- open the page in a browser if possible - confirm the LIVE DATA banner and tooltip look right

## 5. Update the docs

Add a row to the `Known working devices` table in `README.md` - vendor, hardware, firmware, which SNMP version(s) actually worked, and any device-specific notes (tooltip behavior, `ifIndex` quirks, anything that surprised you). Don't mark a version ✅ unless you completed step 4 for it - a connectivity check alone isn't "confirmed end-to-end" by this project's own stated bar.
