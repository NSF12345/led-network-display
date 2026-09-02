"""
Turns smoothed RX/TX byte rates into a moving-particle animation frame:
a list of (r, g, b) tuples, one per LED.

RX particles travel low-index -> high-index (cyan by default).
TX particles travel high-index -> low-index (green by default).
Traffic rate controls spawn frequency; heavier traffic also brightens
and lengthens trails slightly, matching the original blog's description.
"""
import colorsys
import math
import random
import time
from dataclasses import dataclass


@dataclass
class Particle:
    position: float  # fractional pixel index
    direction: int    # +1 or -1
    brightness: float  # 0.0-1.0
    trail: float        # trail length in pixels
    speed: float         # pixels per second, jittered per-particle
    # True only for particles spawned during a manual inject burst - lets
    # render() optionally exclude them (e.g. from the WLED-bound frame).
    injected: bool = False
    # Optional color override. None for normal particles.
    hue: float | None = None


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
        # Manual inject burst (web UI buttons) - independent of the actual
        # traffic rate/source, so it works whether real traffic is idle or
        # maxed out. {direction: expiry monotonic time}.
        self._burst_until = {"rx": 0.0, "tx": 0.0}
        # Burst trigger covering both directions at once - see trigger_rainbow_burst().
        self._rainbow_until = 0.0

    @property
    def rx_rate(self) -> float:
        return self._rx_rate

    @property
    def tx_rate(self) -> float:
        return self._tx_rate

    def update_rates(self, rx_bytes_per_sec: float, tx_bytes_per_sec: float):
        self._rx_rate = rx_bytes_per_sec
        self._tx_rate = tx_bytes_per_sec

    def inject(self, direction: str) -> None:
        """Triggers a particle burst on the given direction ("rx" or "tx")
        for INJECT_BURST_DURATION_SECONDS, regardless of the current
        traffic rate or source. Also spawns an immediate tight cluster of
        particles, so it reads as an obvious "pulse" rather than just
        gradually heavier traffic."""
        if direction not in self._burst_until:
            raise ValueError(f"Unknown direction: {direction!r} (expected 'rx' or 'tx')")
        self._burst_until[direction] = time.monotonic() + self.cfg.INJECT_BURST_DURATION_SECONDS
        self._spawn_cluster(direction)

    def trigger_rainbow_burst(self) -> None:
        """Triggers a burst on both directions at once for
        INJECT_BURST_DURATION_SECONDS, with each spawned particle getting a
        random color instead of the usual RX/TX one."""
        self._rainbow_until = time.monotonic() + self.cfg.INJECT_BURST_DURATION_SECONDS

    def _spawn_cluster(self, direction: str, cluster_size: int = 12, spacing: float = 0.5) -> None:
        particles = self._rx_particles if direction == "rx" else self._tx_particles
        dir_sign = +1 if direction == "rx" else -1
        base_speed = (self.cfg.RX_PARTICLE_SPEED_PIXELS_PER_SEC if direction == "rx"
                      else self.cfg.TX_PARTICLE_SPEED_PIXELS_PER_SEC)
        start_pos = 0.0 if dir_sign == 1 else float(self.led_count - 1)
        jitter = self.cfg.PARTICLE_SPEED_JITTER
        room = max(0, self.cfg.PARTICLE_MAX_PER_DIRECTION - len(particles))
        for i in range(min(cluster_size, room)):
            speed = base_speed * (1.0 - jitter + random.random() * 2 * jitter)
            particles.append(Particle(
                position=start_pos + dir_sign * i * spacing,
                direction=dir_sign, brightness=1.0,
                trail=self.cfg.PARTICLE_TRAIL_LENGTH * 2.0, speed=speed, injected=True))

    def _maybe_spawn(self, particles: list[Particle], rate: float, direction: int, dt: float,
                      accumulator_attr: str, base_speed: float, injected: bool, rainbow: bool):
        intensity = _rate_to_intensity(rate, self.cfg.RATE_SCALE_MIN_BYTES, self.cfg.RATE_SCALE_MAX_BYTES)
        if injected:
            intensity = max(intensity, 1.0)  # visible even if real traffic is idle
        if intensity <= 0.0:
            return
        # Spawn rate scales with intensity: up to ~15 particles/sec at max traffic.
        spawns_per_sec = intensity * 15.0
        acc = getattr(self, accumulator_attr) + spawns_per_sec * dt
        max_particles = self.cfg.PARTICLE_MAX_PER_DIRECTION
        jitter = self.cfg.PARTICLE_SPEED_JITTER
        while acc >= 1.0:
            acc -= 1.0
            if len(particles) >= max_particles:
                continue
            start_pos = 0.0 if direction == 1 else float(self.led_count - 1)
            brightness = 0.5 + 0.5 * intensity  # heavier traffic -> brighter
            trail = self.cfg.PARTICLE_TRAIL_LENGTH * (1.0 + intensity)  # and longer trail
            speed = base_speed * (1.0 - jitter + random.random() * 2 * jitter)
            hue = random.random() if rainbow else None
            particles.append(Particle(position=start_pos, direction=direction, brightness=brightness,
                                       trail=trail, speed=speed, injected=injected, hue=hue))
        setattr(self, accumulator_attr, acc)

    def advance(self, dt: float) -> None:
        """Steps the particle simulation (spawning + physics) by dt seconds,
        without rendering a frame - call render() separately to get one."""
        now = time.monotonic()
        rainbow = now < self._rainbow_until
        rx_injected = now < self._burst_until["rx"] or rainbow
        tx_injected = now < self._burst_until["tx"] or rainbow
        self._maybe_spawn(self._rx_particles, self._rx_rate, +1, dt, "_spawn_accumulator_rx",
                           self.cfg.RX_PARTICLE_SPEED_PIXELS_PER_SEC, rx_injected, rainbow)
        self._maybe_spawn(self._tx_particles, self._tx_rate, -1, dt, "_spawn_accumulator_tx",
                           self.cfg.TX_PARTICLE_SPEED_PIXELS_PER_SEC, tx_injected, rainbow)

        for p in self._rx_particles:
            p.position += p.direction * p.speed * dt
        for p in self._tx_particles:
            p.position += p.direction * p.speed * dt

        self._rx_particles = [p for p in self._rx_particles if -p.trail <= p.position <= self.led_count - 1 + p.trail]
        self._tx_particles = [p for p in self._tx_particles if -p.trail <= p.position <= self.led_count - 1 + p.trail]

    def render(self, include_injected: bool = True) -> list[tuple[int, int, int]]:
        """Paints the current particle state into a frame, optionally
        excluding manually-injected particles (e.g. for a WLED sink that
        hasn't opted into seeing injects)."""
        rx = self._rx_particles if include_injected else [p for p in self._rx_particles if not p.injected]
        tx = self._tx_particles if include_injected else [p for p in self._tx_particles if not p.injected]

        frame = [[0.0, 0.0, 0.0] for _ in range(self.led_count)]
        self._paint(frame, rx, self.cfg.RX_COLOR, self.cfg.RX_HIGHLIGHT_COLOR)
        self._paint(frame, tx, self.cfg.TX_COLOR, self.cfg.TX_HIGHLIGHT_COLOR)

        return [
            (min(255, int(r)), min(255, int(g)), min(255, int(b)))
            for r, g, b in frame
        ]

    def _paint(self, frame, particles: list[Particle], color: tuple[int, int, int],
               highlight_color: tuple[int, int, int]):
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
                if p.hue is not None:
                    r_h, g_h, b_h = colorsys.hsv_to_rgb(p.hue, 1.0, 1.0)
                    r_c, g_c, b_c = r_h * 255, g_h * 255, b_h * 255
                else:
                    # Blend from the bright highlight color at the head toward
                    # the base color along the trail.
                    blend = fade
                    r_c = highlight_color[0] * blend + color[0] * (1 - blend)
                    g_c = highlight_color[1] * blend + color[1] * (1 - blend)
                    b_c = highlight_color[2] * blend + color[2] * (1 - blend)
                for idx, weight in ((idx_low, 1 - frac), (idx_high, frac)):
                    if 0 <= idx < self.led_count and weight > 0:
                        frame[idx][0] += r_c * b * weight
                        frame[idx][1] += g_c * b * weight
                        frame[idx][2] += b_c * b * weight
