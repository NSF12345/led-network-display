"""
Turns smoothed RX/TX byte rates into a moving-particle animation frame:
a list of (r, g, b) tuples, one per LED.

RX particles travel low-index -> high-index (cyan by default).
TX particles travel high-index -> low-index (green by default).
Traffic rate controls spawn frequency; heavier traffic also brightens
and lengthens trails slightly, matching the original blog's description.
"""
import math
import random
from dataclasses import dataclass


@dataclass
class Particle:
    position: float  # fractional pixel index
    direction: int    # +1 or -1
    brightness: float  # 0.0-1.0
    trail: float        # trail length in pixels


def _rate_to_intensity(rate_bytes_per_sec: float, min_bytes: float, max_bytes: float) -> float:
    """Log-scale a byte rate to a 0.0-1.0 intensity, since traffic spans
    orders of magnitude and a linear map would make anything short of
    a firehose look identical to idle."""
    if rate_bytes_per_sec <= min_bytes:
        return 0.0
    if rate_bytes_per_sec >= max_bytes:
        return 1.0
    log_min = math.log10(min_bytes)
    log_max = math.log10(max_bytes)
    log_val = math.log10(rate_bytes_per_sec)
    return (log_val - log_min) / (log_max - log_min)


class ParticleRenderer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.led_count = cfg.LED_COUNT
        self._rx_particles: list[Particle] = []
        self._tx_particles: list[Particle] = []
        self._rx_rate = 0.0
        self._tx_rate = 0.0
        self._spawn_accumulator_rx = 0.0
        self._spawn_accumulator_tx = 0.0

    def update_rates(self, rx_bytes_per_sec: float, tx_bytes_per_sec: float):
        self._rx_rate = rx_bytes_per_sec
        self._tx_rate = tx_bytes_per_sec

    def _maybe_spawn(self, particles: list[Particle], rate: float, direction: int, dt: float, accumulator_attr: str):
        intensity = _rate_to_intensity(rate, self.cfg.RATE_SCALE_MIN_BYTES, self.cfg.RATE_SCALE_MAX_BYTES)
        if intensity <= 0.0:
            return
        # Spawn rate scales with intensity: up to ~15 particles/sec at max traffic.
        spawns_per_sec = intensity * 15.0
        acc = getattr(self, accumulator_attr) + spawns_per_sec * dt
        while acc >= 1.0:
            start_pos = 0.0 if direction == 1 else float(self.led_count - 1)
            brightness = 0.5 + 0.5 * intensity  # heavier traffic -> brighter
            trail = self.cfg.PARTICLE_TRAIL_LENGTH * (1.0 + intensity)  # and longer trail
            particles.append(Particle(position=start_pos, direction=direction, brightness=brightness, trail=trail))
            acc -= 1.0
        setattr(self, accumulator_attr, acc)

    def step(self, dt: float) -> list[tuple[int, int, int]]:
        """Advance the simulation by dt seconds and return the rendered frame."""
        self._maybe_spawn(self._rx_particles, self._rx_rate, +1, dt, "_spawn_accumulator_rx")
        self._maybe_spawn(self._tx_particles, self._tx_rate, -1, dt, "_spawn_accumulator_tx")

        speed = self.cfg.PARTICLE_SPEED_PIXELS_PER_SEC
        for p in self._rx_particles:
            p.position += p.direction * speed * dt
        for p in self._tx_particles:
            p.position += p.direction * speed * dt

        self._rx_particles = [p for p in self._rx_particles if -p.trail <= p.position <= self.led_count - 1 + p.trail]
        self._tx_particles = [p for p in self._tx_particles if -p.trail <= p.position <= self.led_count - 1 + p.trail]

        frame = [[0.0, 0.0, 0.0] for _ in range(self.led_count)]
        self._paint(frame, self._rx_particles, self.cfg.RX_COLOR)
        self._paint(frame, self._tx_particles, self.cfg.TX_COLOR)

        return [
            (min(255, int(r)), min(255, int(g)), min(255, int(b)))
            for r, g, b in frame
        ]

    def _paint(self, frame, particles: list[Particle], color: tuple[int, int, int]):
        for p in particles:
            # Fractional-pixel interpolation: light the two nearest LEDs
            # in proportion to how close the particle is to each, then
            # fall off across the trail length.
            head = p.position
            trail_px = max(1.0, p.trail)
            steps = int(trail_px * 2)  # sample trail at sub-pixel resolution
            for i in range(steps + 1):
                offset = (i / steps) * trail_px if steps > 0 else 0.0
                pos = head - p.direction * offset
                fade = max(0.0, 1.0 - offset / trail_px)
                idx_low = math.floor(pos)
                idx_high = idx_low + 1
                frac = pos - idx_low
                b = p.brightness * fade
                for idx, weight in ((idx_low, 1 - frac), (idx_high, frac)):
                    if 0 <= idx < self.led_count and weight > 0:
                        frame[idx][0] += color[0] * b * weight
                        frame[idx][1] += color[1] * b * weight
                        frame[idx][2] += color[2] * b * weight
