"""
Central config, loaded from environment variables (see .env.example).
Fails loudly on startup if required SNMPv3 fields are missing — better
than silently polling with broken auth.
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
    # --- SNMP target ---
    SNMP_HOST = _get("SNMP_HOST", required=True)
    SNMP_PORT = _get_int("SNMP_PORT", 161)
    SNMP_IF_INDEX = _get_int("SNMP_IF_INDEX", required=True)  # ifIndex of the port to monitor

    # SNMPv3 auth (USM)
    SNMP_USER = _get("SNMP_USER", required=True)
    SNMP_AUTH_PROTOCOL = _get("SNMP_AUTH_PROTOCOL", "SHA")   # MD5 | SHA | SHA224 | SHA256 | SHA384 | SHA512
    SNMP_AUTH_PASSWORD = _get("SNMP_AUTH_PASSWORD", required=True)
    SNMP_PRIV_PROTOCOL = _get("SNMP_PRIV_PROTOCOL", "AES128")  # DES | AES128 | AES192 | AES256
    SNMP_PRIV_PASSWORD = _get("SNMP_PRIV_PASSWORD", required=True)
    SNMP_CONTEXT_NAME = _get("SNMP_CONTEXT_NAME", "")

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

    RX_COLOR = tuple(int(x) for x in _get("RX_COLOR", "0,255,255").split(","))  # cyan
    TX_COLOR = tuple(int(x) for x in _get("TX_COLOR", "0,255,0").split(","))    # green

    PARTICLE_SPEED_PIXELS_PER_SEC = _get_float("PARTICLE_SPEED_PIXELS_PER_SEC", 60.0)
    PARTICLE_TRAIL_LENGTH = _get_float("PARTICLE_TRAIL_LENGTH", 3.0)

    # --- Output sinks ---
    WEB_ENABLED = _get("WEB_ENABLED", "true").lower() == "true"
    WEB_HOST = _get("WEB_HOST", "0.0.0.0")
    WEB_PORT = _get_int("WEB_PORT", 8080)

    WLED_ENABLED = _get("WLED_ENABLED", "false").lower() == "true"
    WLED_HOST = _get("WLED_HOST", "")
    WLED_PORT = _get_int("WLED_PORT", 21324)  # WLED default realtime UDP port
    WLED_TIMEOUT_SECONDS = _get_int("WLED_TIMEOUT_SECONDS", 5)  # realtime fallback timeout


config = Config()
