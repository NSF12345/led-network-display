from dataclasses import dataclass


@dataclass
class TrafficRates:
    rx_bytes_per_sec: float
    tx_bytes_per_sec: float
