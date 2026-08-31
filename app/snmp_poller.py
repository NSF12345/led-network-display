"""
Polls a single interface's octet counters (IF-MIB) over SNMP (v1, v2c, or
v3, per cfg.SNMP_VERSION) and turns successive samples into smoothed
bytes/sec rates for RX and TX. v2c/v3 use the 64-bit ifHCInOctets/
ifHCOutOctets; v1 falls back to the older 32-bit ifInOctets/ifOutOctets,
since SNMPv1's PDU encoding can't carry Counter64 at all.

Uses raw numeric OIDs (1.3.6.1.2.1.31.1.1.1.6/.10 + ifIndex) rather than
symbolic MIB names (ObjectIdentity("IF-MIB", "ifHCInOctets", idx)) -
verified against a real install that the IF-MIB module isn't bundled with
pysnmp-lextudio, so symbolic resolution throws MibNotFoundError. Numeric
OIDs skip MIB compilation entirely and are standard practice for exactly
this reason.

Verified against pysnmp-lextudio 6.3.0 (6.1.4 from early planning doesn't
exist on PyPI): the installed API is pysnmp.hlapi.asyncio (not
hlapi.v3arch.asyncio), the fetch function is getCmd (not get_cmd), and
UdpTransportTarget is a plain sync constructor (not an async .create()).
Confirmed end-to-end against an unreachable test address (192.0.2.1) -
request builds and sends correctly, times out as expected. Not yet
confirmed against a real device's actual SNMPv3 credentials.
"""
import asyncio
import logging
import time

from .traffic_rates import TrafficRates
from pysnmp.hlapi.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    UsmUserData,
    getCmd,
    usmAesCfb128Protocol,
    usmAesCfb192Protocol,
    usmAesCfb256Protocol,
    usmDESPrivProtocol,
    usmHMAC128SHA224AuthProtocol,
    usmHMAC192SHA256AuthProtocol,
    usmHMAC256SHA384AuthProtocol,
    usmHMAC384SHA512AuthProtocol,
    usmHMACMD5AuthProtocol,
    usmHMACSHAAuthProtocol,
    usmNoPrivProtocol,
)

log = logging.getLogger("snmp_poller")

# IF-MIB ifHCInOctets / ifHCOutOctets (64-bit, Counter64), addressed
# numerically (see module docstring). Used for v2c/v3.
IF_HC_IN_OCTETS_OID = "1.3.6.1.2.1.31.1.1.1.6"
IF_HC_OUT_OCTETS_OID = "1.3.6.1.2.1.31.1.1.1.10"

# IF-MIB ifInOctets / ifOutOctets (32-bit, Counter32, RFC1213) - SNMPv1's
# PDU encoding can't carry Counter64, so v1 falls back to these. Wraps
# at 4GB, which happens often on a busy link (~34s sustained at 1Gbps) -
# a wrap is treated the same as a counter reset (see _apply_sample),
# which means a dropped sample rather than a corrected delta. Acceptable
# for this project's purposes but worth knowing if v1 traffic looks
# choppier than v2c/v3 on fast links.
IF_IN_OCTETS_OID = "1.3.6.1.2.1.2.2.1.10"
IF_OUT_OCTETS_OID = "1.3.6.1.2.1.2.2.1.16"

# For display only (which switch, which physical port) - not part of the
# per-second polling loop.
SYS_NAME_OID = "1.3.6.1.2.1.1.5.0"      # SNMPv2-MIB sysName
SYS_DESCR_OID = "1.3.6.1.2.1.1.1.0"     # SNMPv2-MIB sysDescr, used as a fallback if sysName is unset
IF_NAME_OID = "1.3.6.1.2.1.31.1.1.1.1"  # IF-MIB ifName, e.g. "0/1" for physical port 1

AUTH_PROTOCOLS = {
    "MD5": usmHMACMD5AuthProtocol,
    "SHA": usmHMACSHAAuthProtocol,
    "SHA224": usmHMAC128SHA224AuthProtocol,
    "SHA256": usmHMAC192SHA256AuthProtocol,
    "SHA384": usmHMAC256SHA384AuthProtocol,
    "SHA512": usmHMAC384SHA512AuthProtocol,
}

PRIV_PROTOCOLS = {
    "DES": usmDESPrivProtocol,
    "AES128": usmAesCfb128Protocol,
    "AES192": usmAesCfb192Protocol,
    "AES256": usmAesCfb256Protocol,
    "NONE": usmNoPrivProtocol,
}


class SnmpPoller:
    def __init__(self, cfg):
        self.cfg = cfg
        self._engine = SnmpEngine()
        if cfg.SNMP_VERSION in ("v1", "v2c"):
            # mpModel: 0 = v1, 1 = v2c - neither is encrypted, the
            # community string is sent in the clear on the wire.
            mp_model = 0 if cfg.SNMP_VERSION == "v1" else 1
            self._auth_data = CommunityData(cfg.SNMP_COMMUNITY, mpModel=mp_model)
        else:
            self._auth_data = UsmUserData(
                cfg.SNMP_USER,
                authKey=cfg.SNMP_AUTH_PASSWORD,
                privKey=cfg.SNMP_PRIV_PASSWORD,
                authProtocol=AUTH_PROTOCOLS[cfg.SNMP_AUTH_PROTOCOL.upper()],
                privProtocol=PRIV_PROTOCOLS[cfg.SNMP_PRIV_PROTOCOL.upper()],
            )
        self._context = ContextData(contextName=cfg.SNMP_CONTEXT_NAME)
        self._transport = UdpTransportTarget(
            (cfg.SNMP_HOST, cfg.SNMP_PORT), timeout=2, retries=1
        )

        self._prev_rx = None
        self._prev_tx = None
        self._prev_time = None
        self._smoothed_rx = 0.0
        self._smoothed_tx = 0.0

    async def _fetch_counters(self):
        if self.cfg.SNMP_VERSION == "v1":
            in_oid, out_oid = IF_IN_OCTETS_OID, IF_OUT_OCTETS_OID
        else:
            in_oid, out_oid = IF_HC_IN_OCTETS_OID, IF_HC_OUT_OCTETS_OID

        error_indication, error_status, error_index, var_binds = await getCmd(
            self._engine,
            self._auth_data,
            self._transport,
            self._context,
            ObjectType(ObjectIdentity(f"{in_oid}.{self.cfg.SNMP_IF_INDEX}")),
            ObjectType(ObjectIdentity(f"{out_oid}.{self.cfg.SNMP_IF_INDEX}")),
        )

        if error_indication:
            raise RuntimeError(f"SNMP error indication: {error_indication}")
        if error_status:
            raise RuntimeError(
                f"SNMP error status: {error_status.prettyPrint()} at "
                f"{var_binds[int(error_index) - 1][0] if error_index else '?'}"
            )

        rx_octets = int(var_binds[0][1])
        tx_octets = int(var_binds[1][1])
        return rx_octets, tx_octets

    def _apply_sample(self, rx_octets: int, tx_octets: int, now: float) -> TrafficRates:
        if self._prev_time is None:
            # First sample: no delta available yet, report zero.
            self._prev_rx, self._prev_tx, self._prev_time = rx_octets, tx_octets, now
            return TrafficRates(0.0, 0.0)

        dt = now - self._prev_time
        if dt <= 0:
            return TrafficRates(self._smoothed_rx, self._smoothed_tx)

        # Guard against counter reset/wrap (interface flap, device reboot):
        # a negative delta means the counter went backwards, so we can't
        # trust this sample as a rate - skip it rather than emit garbage.
        d_rx = rx_octets - self._prev_rx
        d_tx = tx_octets - self._prev_tx
        if d_rx < 0 or d_tx < 0:
            log.warning("Counter went backwards (reset/wrap?) - skipping sample")
            self._prev_rx, self._prev_tx, self._prev_time = rx_octets, tx_octets, now
            return TrafficRates(self._smoothed_rx, self._smoothed_tx)

        raw_rx = d_rx / dt
        raw_tx = d_tx / dt

        alpha = self.cfg.RATE_SMOOTHING_ALPHA
        self._smoothed_rx = alpha * raw_rx + (1 - alpha) * self._smoothed_rx
        self._smoothed_tx = alpha * raw_tx + (1 - alpha) * self._smoothed_tx

        self._prev_rx, self._prev_tx, self._prev_time = rx_octets, tx_octets, now
        return TrafficRates(self._smoothed_rx, self._smoothed_tx)

    async def get_device_info(self) -> dict:
        """One-off lookup of human-readable device identity (switch name,
        physical port label) for display in the web preview - not part of
        the per-second polling loop. Best-effort: returns {} on failure
        rather than blocking startup over a cosmetic lookup."""
        try:
            error_indication, error_status, error_index, var_binds = await getCmd(
                self._engine,
                self._auth_data,
                self._transport,
                self._context,
                ObjectType(ObjectIdentity(SYS_NAME_OID)),
                ObjectType(ObjectIdentity(SYS_DESCR_OID)),
                ObjectType(ObjectIdentity(f"{IF_NAME_OID}.{self.cfg.SNMP_IF_INDEX}")),
            )
            if error_indication or error_status:
                log.warning("Could not fetch device info: %s", error_indication or error_status.prettyPrint())
                return {}
            sys_name = str(var_binds[0][1]).strip()
            sys_descr = str(var_binds[1][1]).strip()
            if_name = str(var_binds[2][1]).strip()
            switch_name = sys_name or sys_descr.split(",")[0].strip() or self.cfg.SNMP_HOST
            return {"switch_name": switch_name, "switch_port": if_name, "sys_descr": sys_descr}
        except Exception:
            log.exception("Failed to fetch device info (non-fatal, continuing)")
            return {}

    async def poll_once(self) -> TrafficRates:
        rx_octets, tx_octets = await self._fetch_counters()
        return self._apply_sample(rx_octets, tx_octets, time.monotonic())

    async def run(self, on_sample):
        """Poll forever at the configured interval, calling on_sample(TrafficRates) each time."""
        interval = self.cfg.POLL_INTERVAL_SECONDS
        while True:
            start = time.monotonic()
            try:
                rates = await self.poll_once()
                on_sample(rates)
            except Exception:
                log.exception("SNMP poll failed - will retry next interval")
            elapsed = time.monotonic() - start
            await asyncio.sleep(max(0.0, interval - elapsed))
