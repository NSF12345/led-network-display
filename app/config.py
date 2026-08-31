"""
Central config, loaded from environment variables (see .env.example).
Fails loudly on startup if required SNMP fields for the selected
SNMP_VERSION are missing - better than silently polling with broken auth.
"""
import os


def _get(name: str, default=None, required: bool = False):
    val = os.environ.get(name, default)
    if required and (val is None or val == ""):
        raise RuntimeError(f"Missing required env var: {name}")
    return val


def _get_int(name: str, default: int = None, required: bool = False) -> int:
    val = os.environ.get(name)
    if val is None or val == "":
        if required:
            raise RuntimeError(f"Missing required env var: {name}")
        return default
    return int(val)


def _get_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


class Config:
    # --- Traffic source ---
    # "dummy" generates synthetic RX/TX traffic - no SNMP target needed, for
    # building/testing the pipeline before a real device is wired up.
    # "snmp" polls a real device (see SnmpPoller) - requires the SNMP_* fields below.
    TRAFFIC_SOURCE = _get("TRAFFIC_SOURCE", "dummy").lower()

    # --- SNMP target (only required when TRAFFIC_SOURCE=snmp) ---
    _snmp_required = TRAFFIC_SOURCE == "snmp"
    SNMP_HOST = _get("SNMP_HOST", required=_snmp_required)
    SNMP_PORT = _get_int("SNMP_PORT", 161)
    SNMP_IF_INDEX = _get_int("SNMP_IF_INDEX", required=_snmp_required)  # ifIndex of the port to monitor

    # "v1"/"v2c" = community-string auth, no encryption - simpler to set up,
    # but sends the community string in the clear. v1 uses the older 32-bit
    # counters (ifInOctets/ifOutOctets) instead of the 64-bit ones, since
    # its PDU encoding can't carry Counter64 - see snmp_poller.py. "v3" =
    # USM auth+privacy, more setup but properly authenticated and encrypted.
    SNMP_VERSION = _get("SNMP_VERSION", "v3").lower()
    if SNMP_VERSION not in ("v1", "v2c", "v3"):
        raise RuntimeError(f"Invalid SNMP_VERSION: {SNMP_VERSION!r} (expected 'v1', 'v2c', or 'v3')")
    _snmp_community_required = _snmp_required and SNMP_VERSION in ("v1", "v2c")
    _snmp_v3_required = _snmp_required and SNMP_VERSION == "v3"

    # SNMPv1/v2c auth (community string)
    SNMP_COMMUNITY = _get("SNMP_COMMUNITY", required=_snmp_community_required)

    # SNMPv3 auth (USM)
    SNMP_USER = _get("SNMP_USER", required=_snmp_v3_required)
    SNMP_AUTH_PROTOCOL = _get("SNMP_AUTH_PROTOCOL", "SHA")   # MD5 | SHA | SHA224 | SHA256 | SHA384 | SHA512
    SNMP_AUTH_PASSWORD = _get("SNMP_AUTH_PASSWORD", required=_snmp_v3_required)
    SNMP_PRIV_PROTOCOL = _get("SNMP_PRIV_PROTOCOL", "AES128")  # DES | AES128 | AES192 | AES256
    SNMP_PRIV_PASSWORD = _get("SNMP_PRIV_PASSWORD", required=_snmp_v3_required)
    SNMP_CONTEXT_NAME = _get("SNMP_CONTEXT_NAME", "")

    # --- Dummy traffic source tuning (only used when TRAFFIC_SOURCE=dummy) ---
    DUMMY_RX_BASELINE_BYTES = _get_float("DUMMY_RX_BASELINE_BYTES", 200_000)
    DUMMY_TX_BASELINE_BYTES = _get_float("DUMMY_TX_BASELINE_BYTES", 50_000)
    DUMMY_SPIKE_CHANCE = _get_float("DUMMY_SPIKE_CHANCE", 0.08)  # probability per sample of a traffic burst
    DUMMY_SPIKE_MAX_BYTES = _get_float("DUMMY_SPIKE_MAX_BYTES", 20_000_000)

    # --- Polling / rendering ---
    POLL_INTERVAL_SECONDS = _get_float("POLL_INTERVAL_SECONDS", 1.0)
    RENDER_FPS = _get_int("RENDER_FPS", 24)
    LED_COUNT = _get_int("LED_COUNT", 180)

    # Smoothing: exponential moving average weight for new samples (0-1).
    # Lower = smoother/slower to react, higher = more responsive/jittery.
    RATE_SMOOTHING_ALPHA = _get_float("RATE_SMOOTHING_ALPHA", 0.3)

    # Traffic-to-particle-rate scaling. Traffic rates span orders of
    # magnitude (KB/s idle to 100+ MB/s busy), so we log-scale before
    # mapping to spawn probability rather than a linear map.
    RATE_SCALE_MIN_BYTES = _get_float("RATE_SCALE_MIN_BYTES", 1_000)        # ~8kbps floor
    RATE_SCALE_MAX_BYTES = _get_float("RATE_SCALE_MAX_BYTES", 50_000_000)  # ~400mbps ceiling

    RX_COLOR = tuple(int(x) for x in _get("RX_COLOR", "0,205,255").split(","))            # cyan
    RX_HIGHLIGHT_COLOR = tuple(int(x) for x in _get("RX_HIGHLIGHT_COLOR", "210,255,255").split(","))  # bright particle head
    TX_COLOR = tuple(int(x) for x in _get("TX_COLOR", "0,255,100").split(","))            # green
    TX_HIGHLIGHT_COLOR = tuple(int(x) for x in _get("TX_HIGHLIGHT_COLOR", "70,255,220").split(","))   # bright particle head

    # Travel speed, per direction (original blog post used 15.0/13.5 LEDs-per-sec
    # on a 90-LED strip; scaled here for LED_COUNT=180 by default).
    RX_PARTICLE_SPEED_PIXELS_PER_SEC = _get_float("RX_PARTICLE_SPEED_PIXELS_PER_SEC", 30.0)
    TX_PARTICLE_SPEED_PIXELS_PER_SEC = _get_float("TX_PARTICLE_SPEED_PIXELS_PER_SEC", 27.0)
    # Per-particle random speed variation, e.g. 0.10 = +/-10%.
    PARTICLE_SPEED_JITTER = _get_float("PARTICLE_SPEED_JITTER", 0.10)
    PARTICLE_TRAIL_LENGTH = _get_float("PARTICLE_TRAIL_LENGTH", 3.0)
    # Cap on live particles per direction, so heavy traffic saturates
    # brightness/spawn-rate instead of piling up indefinitely.
    PARTICLE_MAX_PER_DIRECTION = _get_int("PARTICLE_MAX_PER_DIRECTION", 24)

    # If no new traffic sample arrives within this many seconds (SNMP target
    # unreachable, etc.), decay rates to zero so the animation fades to idle
    # instead of looping the last-known traffic forever.
    STALE_DATA_TIMEOUT_SECONDS = _get_float("STALE_DATA_TIMEOUT_SECONDS", 3.0)

    # --- Output sinks ---
    WEB_ENABLED = _get("WEB_ENABLED", "true").lower() == "true"
    WEB_HOST = _get("WEB_HOST", "0.0.0.0")
    WEB_PORT = _get_int("WEB_PORT", 8080)

    WLED_ENABLED = _get("WLED_ENABLED", "false").lower() == "true"
    WLED_HOST = _get("WLED_HOST", "")
    WLED_PORT = _get_int("WLED_PORT", 21324)  # WLED default realtime UDP port
    WLED_TIMEOUT_SECONDS = _get_int("WLED_TIMEOUT_SECONDS", 5)  # realtime fallback timeout


config = Config()
