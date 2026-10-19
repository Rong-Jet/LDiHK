"""Synthetic comparison population, computed on demand for any date range
and any set of platforms (one platform, or total social media time).

The profiles (age range, sex, personal volume, sessions per day, chronotype)
come from backend/synthetic_population.py and its study calibration. Instead
of storing their events, each profile's YouTube watch time on a day is a
deterministic function of the profile and the date, so the same day always
gives the same value, any range (also years back) works, and nothing is stored
in the database.

Daily hours = personal median (summed over the requested platforms) x weekday x season x long-term trend x personal
drift x life events x day-to-day noise, with some days without use:

- weekday factors, day-to-day noise and days without use: as in
  synthetic_population.py.
- season [assumption]: teenagers watch more in the summer and Christmas
  holidays and around Easter; adults somewhat more in the dark months and over
  Christmas, a little less in the summer. Normalised to a yearly mean of 1.
- public holidays count as Sundays (fixed-date German holidays).
- trend [assumption]: about +4% YouTube time per year (relative to 2024).
- personal drift: each profile's habits change slowly (three slow waves with
  periods of 4 weeks to a year, about +-30% together).
- life events [assumption]: in about 4% of two-week blocks a profile is away
  (holiday, exams; 15% of usual use), in about 5% it binges (1.7x).

Hour of day, late-night share and fragmentation follow the profile's
chronotype-shifted hour curve and its session rate.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

import numpy as np

from backend import synthetic_population as model

MODEL_VERSION = "procedural_usage.v2"
SOCIAL_PLATFORMS = model.SOCIAL_PLATFORMS
POPULATION_SIZE = 1500
POPULATION_SEED = 20261019
EPOCH = date(2010, 1, 1)
# Above this many profile-days a request uses an evenly spread subset of the
# profiles (percentiles stay stable, memory stays small on a 512 MB instance).
MAX_CELLS = 1_500_000
MAX_DAILY_HOURS = 16.0

LATE_NIGHT_HOURS = (23, 0, 1, 2, 3, 4)
ACTIVE_HOUR_MINUTES = 5.0

TREND_PER_YEAR = 0.04
TREND_REFERENCE_YEAR = 2024
DRIFT_AMPLITUDE = 0.3
BLOCK_DAYS = 14
AWAY_SHARE, AWAY_FACTOR = 0.04, 0.15
BINGE_SHARE, BINGE_FACTOR = 0.05, 1.7
# Fixed-date public holidays (Germany), treated like Sundays.
PUBLIC_HOLIDAYS = ((1, 1), (5, 1), (10, 3), (12, 25), (12, 26))


@dataclass(frozen=True)
class SyntheticProfile:
    index: int
    age_range: str
    sex: str
    model_group: str
    # Median minutes per day per platform (0 = does not use it).
    platform_minutes: tuple[tuple[str, float], ...]
    # Sessions per day across all platforms.
    sessions_per_day: float
    # Share of the day's watching per hour (24 values each).
    weekday_hours: tuple[float, ...]
    weekend_hours: tuple[float, ...]
    drift: tuple[tuple[float, float, float], ...]  # (amplitude, period days, phase)
    block_offset: int

    @property
    def user_id(self) -> str:
        return f"synthetic-{self.index:05d}"

    def minutes_on(self, platforms: tuple[str, ...]) -> float:
        return sum(minutes for platform, minutes in self.platform_minutes if platform in platforms)


@lru_cache(maxsize=1)
def population() -> tuple[SyntheticProfile, ...]:
    """POPULATION_SIZE generated profiles (fixed seed)."""
    rng = random.Random(POPULATION_SEED)
    profiles = []
    for index in range(POPULATION_SIZE):
        persona = model.generate_persona(rng)
        drift = tuple(
            (
                DRIFT_AMPLITUDE / math.sqrt(1.5) * rng.uniform(0.5, 1.0),
                rng.uniform(28, 365),
                rng.uniform(0, 2 * math.pi),
            )
            for _ in range(3)
        )
        block_offset = rng.randrange(BLOCK_DAYS)
        profiles.append(
            SyntheticProfile(
                index=index,
                age_range=persona.age_range,
                sex=persona.sex,
                model_group=persona.model_group,
                platform_minutes=tuple(persona.daily_minutes.items()),
                sessions_per_day=persona.sessions_per_day,
                weekday_hours=_hour_shares(persona.model_group, "weekday", persona.chronotype_shift),
                weekend_hours=_hour_shares(persona.model_group, "weekend", persona.chronotype_shift),
                drift=drift,
                block_offset=block_offset,
            )
        )
    return tuple(profiles)


@dataclass
class DaySeries:
    """Per profile (rows) and day (columns), for one date range."""

    profiles: tuple[SyntheticProfile, ...]
    days: list[date]
    hours: np.ndarray
    late_night_hours: np.ndarray
    # Share of the day's hours with at least 5 minutes of watching (0-1).
    fragmentation: np.ndarray
    # Watch seconds per hour of day over the whole range (profiles x 24).
    hourly_seconds: np.ndarray


def day_series(
    start: date,
    end: date,
    profiles: tuple[SyntheticProfile, ...] | None = None,
    *,
    platforms: tuple[str, ...] = ("youtube",),
) -> DaySeries:
    """Usage on `platforms` (summed) of the profiles that use any of them."""
    platforms = tuple(platforms)
    profiles = population() if profiles is None else profiles
    profiles = tuple(profile for profile in profiles if profile.minutes_on(platforms) > 0)
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    if len(profiles) * len(days) > MAX_CELLS:
        step = math.ceil(len(profiles) * len(days) / MAX_CELLS)
        profiles = profiles[::step]
    n_days = len(days)
    t = np.array([(day - EPOCH).days for day in days], dtype=np.int64)
    idx = np.array([profile.index for profile in profiles], dtype=np.uint64)[:, None]
    groups = [profile.model_group for profile in profiles]

    weekday = np.array([day.weekday() for day in days])
    holiday = np.array([(day.month, day.day) in PUBLIC_HOLIDAYS for day in days])
    weekday = np.where(holiday, 6, weekday)
    weekend = weekday >= 5

    weekday_factor = np.empty((len(profiles), n_days), dtype=np.float64)
    season = np.empty_like(weekday_factor)
    zero_share = np.empty((len(profiles), 1))
    for group in model.WEEKDAY_FACTORS:
        rows = [i for i, g in enumerate(groups) if g == group]
        if not rows:
            continue
        weekday_factor[rows] = np.asarray(model.WEEKDAY_FACTORS[group])[weekday]
        season[rows] = _season(group, days)
        zero_share[rows] = model.ZERO_DAY_SHARE[group]

    years = np.array([day.year + (day.timetuple().tm_yday - 1) / 365.25 for day in days])
    trend = (1 + TREND_PER_YEAR) ** (years - TREND_REFERENCE_YEAR)

    drift = np.zeros((len(profiles), n_days))
    for row, profile in enumerate(profiles):
        for amplitude, period, phase in profile.drift:
            drift[row] += amplitude * np.sin(2 * np.pi * t / period + phase)

    offsets = np.array([profile.block_offset for profile in profiles])[:, None]
    block = ((t[None, :] + offsets) // BLOCK_DAYS).astype(np.uint64)
    block_roll = _uniform(idx, block, 1)
    events = np.where(block_roll < AWAY_SHARE, AWAY_FACTOR, np.where(block_roll > 1 - BINGE_SHARE, BINGE_FACTOR, 1.0))

    day_key = t.astype(np.uint64)[None, :]
    noise = np.exp(model.DAY_TO_DAY_SIGMA * _normal(idx, day_key, 2))
    zero_day = _uniform(idx, day_key, 4) < np.where(events == AWAY_FACTOR, 0.5, zero_share)

    medians = np.array([profile.minutes_on(platforms) for profile in profiles])[:, None]
    minutes = medians * weekday_factor * season * trend[None, :] * np.exp(drift) * events * noise
    minutes = np.where(zero_day, 0.0, np.minimum(minutes, MAX_DAILY_HOURS * 60))
    hours = minutes / 60

    shares_weekday = np.array([profile.weekday_hours for profile in profiles])
    shares_weekend = np.array([profile.weekend_hours for profile in profiles])
    late = [hour in LATE_NIGHT_HOURS for hour in range(24)]
    late_share = np.where(weekend[None, :], shares_weekend[:, late].sum(1)[:, None], shares_weekday[:, late].sum(1)[:, None])
    hourly_seconds = (
        (hours * ~weekend[None, :]).sum(1)[:, None] * shares_weekday
        + (hours * weekend[None, :]).sum(1)[:, None] * shares_weekend
    ) * 3600

    # Sessions that day (more on heavier days, sublinearly), each at least
    # one active hour if it lasts 5 minutes; long sessions span several hours.
    # The sessions that fall on these platforms (their share of all the person's time).
    rate = np.array([
        max(0.5, profile.sessions_per_day * profile.minutes_on(platforms) / max(profile.minutes_on(model.PLATFORMS), 1e-6))
        for profile in profiles
    ])[:, None]
    level = minutes / np.maximum(medians, 1e-6)
    sessions = np.floor(rate * np.power(np.maximum(level, 1e-6), 0.4) + _uniform(idx, day_key, 5))
    sessions = np.where(minutes > 0, np.maximum(sessions, 1), 0)
    per_session = np.divide(minutes, sessions, out=np.zeros_like(minutes), where=sessions > 0)
    hours_per_session = np.where(per_session >= ACTIVE_HOUR_MINUTES, np.maximum(1, np.round(per_session / 60 + 0.3)), 0)
    fragmentation = np.minimum(24, sessions * hours_per_session) / 24

    return DaySeries(
        profiles=profiles,
        days=days,
        hours=hours,
        late_night_hours=hours * late_share,
        fragmentation=fragmentation,
        hourly_seconds=hourly_seconds,
    )


def _hour_shares(group: str, kind: str, shift_hours: float) -> tuple[float, ...]:
    """The group's hour curve moved later by `shift_hours` (fractional, wrapping)."""
    weights = np.asarray(model.HOURLY_WEIGHTS[group][kind], dtype=float)
    whole = math.floor(shift_hours)
    fraction = shift_hours - whole
    shifted = (1 - fraction) * np.roll(weights, whole) + fraction * np.roll(weights, whole + 1)
    return tuple((shifted / shifted.sum()).tolist())


@lru_cache(maxsize=None)
def _season_curve(group: str) -> tuple[float, ...]:
    """Factor per day of the year (366 values), mean 1 over a year."""
    factors = []
    for doy in range(1, 367):
        day = date(2024, 1, 1) + timedelta(days=doy - 1)  # a leap year covers every doy
        winter = math.cos(2 * math.pi * (doy - 15) / 365.25)  # +1 mid-January, -1 mid-July
        christmas = day.month == 12 and day.day >= 22 or day.month == 1 and day.day <= 6
        summer = (day.month == 7 and day.day >= 20) or day.month == 8 or (day.month == 9 and day.day <= 5)
        easter = (day.month == 3 and day.day >= 28) or (day.month == 4 and day.day <= 12)
        if group == "adolescent":
            factor = 1 + 0.05 * winter + 0.25 * summer + 0.20 * christmas + 0.12 * easter
        elif group == "young_adult":
            factor = 1 + 0.08 * winter + 0.12 * christmas - 0.05 * summer
        else:
            factor = 1 + 0.10 * winter + 0.08 * christmas
        factors.append(factor)
    mean = sum(factors) / len(factors)
    return tuple(factor / mean for factor in factors)


def _season(group: str, days: list[date]) -> np.ndarray:
    curve = _season_curve(group)
    return np.array([curve[day.timetuple().tm_yday - 1] for day in days])


_MASK = np.uint64(0xFFFFFFFFFFFFFFFF)


def _mix(values: np.ndarray) -> np.ndarray:
    """splitmix64 finaliser: a fast, well-spread integer hash."""
    with np.errstate(over="ignore"):
        z = values + np.uint64(0x9E3779B97F4A7C15)
        z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        return z ^ (z >> np.uint64(31))


def _uniform(profile: np.ndarray, key: np.ndarray, stream: int) -> np.ndarray:
    """Deterministic uniform [0, 1) per (profile, key, stream)."""
    with np.errstate(over="ignore"):
        seed = np.uint64(POPULATION_SEED) * np.uint64(0x100000001B3) + np.uint64(stream)
        mixed = _mix(_mix(profile * np.uint64(0x9E3779B1) ^ seed) ^ key.astype(np.uint64))
    return (mixed >> np.uint64(11)).astype(np.float64) * (1.0 / (1 << 53))


def _normal(profile: np.ndarray, key: np.ndarray, stream: int) -> np.ndarray:
    u1 = np.maximum(_uniform(profile, key, stream), 1e-12)
    u2 = _uniform(profile, key, stream + 1)
    return np.sqrt(-2 * np.log(u1)) * np.cos(2 * np.pi * u2)
