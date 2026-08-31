"""
Polls a single interface's 64-bit octet counters (ifHCInOctets/ifHCOutOctets,
IF-MIB) over SNMPv3 and turns successive samples into smoothed bytes/sec
rates for RX and TX.

NOTE: written against pysnmp-lextudio 6.x's asyncio v3arch API
(pysnmp.hlapi.v3arch.asyncio). This has NOT been tested against a live
device — pysnmp's high-level API has shifted across major versions before.
If imports/calls fail on your install, run `pip show pysnmp` and check
that against the pysnmp docs for your version; the SNMP mechanics here
(USM auth/priv setup, ifHCInOctets/ifHCOutOctets OIDs) are correct
regardless of which exact API shape your installed version expects.
"""
import asyncio
import logging
import time

from .traffic_rates import TrafficRates
from pysnmp.hlapi.v3arch.asyncio import (
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    UsmUserData,
    get_cmd,
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
        self._user_data = UsmUserData(
            cfg.SNMP_USER,
            authKey=cfg.SNMP_AUTH_PASSWORD,
            privKey=cfg.SNMP_PRIV_PASSWORD,
            authProtocol=AUTH_PROTOCOLS[cfg.SNMP_AUTH_PROTOCOL.upper()],
            privProtocol=PRIV_PROTOCOLS[cfg.SNMP_PRIV_PROTOCOL.upper()],
        )
        self._context = ContextData(contextName=cfg.SNMP_CONTEXT_NAME)
        self._transport = None  # created lazily, see _get_transport

        self._prev_rx = None
        self._prev_tx = None
        self._prev_time = None
        self._smoothed_rx = 0.0
        self._smoothed_tx = 0.0

    async def _get_transport(self):
        if self._transport is None:
            self._transport = await UdpTransportTarget.create(
                (self.cfg.SNMP_HOST, self.cfg.SNMP_PORT)
            )
        return self._transport

    async def _fetch_counters(self):
        transport = await self._get_transport()
        error_indication, error_status, error_index, var_binds = await get_cmd(
            self._engine,
            self._user_data,
            transport,
            self._context,
            ObjectType(ObjectIdentity("IF-MIB", "ifHCInOctets", self.cfg.SNMP_IF_INDEX)),
            ObjectType(ObjectIdentity("IF-MIB", "ifHCOutOctets", self.cfg.SNMP_IF_INDEX)),
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
        # trust this sample as a rate — skip it rather than emit garbage.
        d_rx = rx_octets - self._prev_rx
        d_tx = tx_octets - self._prev_tx
        if d_rx < 0 or d_tx < 0:
            log.warning("Counter went backwards (reset/wrap?) — skipping sample")
            self._prev_rx, self._prev_tx, self._prev_time = rx_octets, tx_octets, now
            return TrafficRates(self._smoothed_rx, self._smoothed_tx)

        raw_rx = d_rx / dt
        raw_tx = d_tx / dt

        alpha = self.cfg.RATE_SMOOTHING_ALPHA
        self._smoothed_rx = alpha * raw_rx + (1 - alpha) * self._smoothed_rx
        self._smoothed_tx = alpha * raw_tx + (1 - alpha) * self._smoothed_tx

        self._prev_rx, self._prev_tx, self._prev_time = rx_octets, tx_octets, now
        return TrafficRates(self._smoothed_rx, self._smoothed_tx)

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
                log.exception("SNMP poll failed — will retry next interval")
            elapsed = time.monotonic() - start
            await asyncio.sleep(max(0.0, interval - elapsed))
