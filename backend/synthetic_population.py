"""Usage model for synthetic comparison profiles (see seed_synthetic_usage.py).

Each profile gets a 5-year age range and a sex, a personal daily volume per
platform drawn from a log-normal distribution (so a realistic minority of
heavy users exists), a personal session rate and chronotype. Each day varies
with the weekday, random day-to-day noise and occasional days without use.
Usage happens in sessions: several videos in a row, each watched for a while,
with the next starting right after. Watch time therefore comes out the same
way it does for real exports (time until the next event).

Calibration. Values marked [study] follow the cited studies; [assumption]
values are plausible defaults that have not been measured and should be
replaced as real data arrives.

- Total social media time per day, adolescents [study]: Riehm et al. (2019,
  JAMA Psychiatry; US, 12-15 y): about 17% no use, 32% up to 30 min, 31% 30 min
  to 3 h, 12% 3-6 h, 8% over 6 h. Kelly et al. (2018, EClinicalMedicine; UK,
  14 y): girls use social media markedly more than boys, with roughly twice
  the share of girls using it 3 h or more a day. The medians below sit between
  the two (current usage is higher than in the 2013-2016 data): about a third
  of girls and a fifth of boys at 3 h or more, about 8% over 6 h.
- Young adults [study]: Lin et al. (2016, Depression and Anxiety; US, 19-32 y):
  median about 61 min a day and about 30 visits a week (about 4 a day).
- Ages 35+ [assumption]: lower and declining with age; no cited source.
- YouTube's share of social media time, the weekday pattern, the hour-of-day
  curves and Shorts versus long videos [assumption].
Verify the [study] figures against the papers before quoting them.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.demographics import AGE_RANGES, age_bounds, model_group

PLATFORMS = ("youtube", "tiktok", "instagram", "spotify", "linkedin")

# Share of social media users in each age range [assumption].
AGE_RANGE_WEIGHTS = {
    "13-14": 4, "15-19": 9, "20-24": 10, "25-29": 10, "30-34": 10, "35-39": 9,
    "40-44": 9, "45-49": 8, "50-54": 8, "55-59": 7, "60-64": 6, "65-69": 5, "70+": 5,
}

# Median total social media minutes per day (female, male); see module notes.
TOTAL_MINUTES_MEDIAN = {
    "13-14": (110, 75), "15-19": (130, 85),            # [study] Riehm 2019, Kelly 2018
    "20-24": (85, 70), "25-29": (70, 60), "30-34": (60, 50),  # [study] Lin 2016
    "35-39": (52, 45), "40-44": (48, 42), "45-49": (44, 40),  # [assumption]
    "50-54": (40, 36), "55-59": (36, 32), "60-64": (32, 28),
    "65-69": (28, 25), "70+": (24, 22),
}

# Spread of personal daily volume (log-normal sigma) per model group. With
# sigma 1.0 the top tenth uses about 3.6 times the median [study: fits the
# Riehm/Kelly tails].
PERSON_SIGMA = {"adolescent": 1.0, "young_adult": 0.95, "older": 0.9}

# Share of social media time per platform (female, male) [assumption].
PLATFORM_SHARE = {
    "adolescent": {
        "female": {"youtube": 0.30, "tiktok": 0.30, "instagram": 0.25, "spotify": 0.15, "linkedin": 0.0},
        "male": {"youtube": 0.50, "tiktok": 0.22, "instagram": 0.13, "spotify": 0.15, "linkedin": 0.0},
    },
    "young_adult": {
        "female": {"youtube": 0.28, "tiktok": 0.22, "instagram": 0.30, "spotify": 0.15, "linkedin": 0.05},
        "male": {"youtube": 0.45, "tiktok": 0.15, "instagram": 0.20, "spotify": 0.13, "linkedin": 0.07},
    },
    "older": {
        "female": {"youtube": 0.38, "tiktok": 0.07, "instagram": 0.30, "spotify": 0.15, "linkedin": 0.10},
        "male": {"youtube": 0.55, "tiktok": 0.05, "instagram": 0.17, "spotify": 0.13, "linkedin": 0.10},
    },
}

# Probability that someone does not use a platform at all [assumption].
NON_USER_SHARE = {
    "adolescent": {"youtube": 0.05, "tiktok": 0.25, "instagram": 0.25, "spotify": 0.35, "linkedin": 1.0},
    "young_adult": {"youtube": 0.07, "tiktok": 0.45, "instagram": 0.25, "spotify": 0.40, "linkedin": 0.60},
    "older": {"youtube": 0.12, "tiktok": 0.85, "instagram": 0.50, "spotify": 0.65, "linkedin": 0.70},
}

# Sessions per day across all platforms (median); Lin 2016: about 4 visits a
# day for young adults [study]; adolescents and older [assumption].
SESSIONS_PER_DAY = {"adolescent": 7.0, "young_adult": 4.5, "older": 3.0}

# Monday..Sunday volume factors (mean 1) [assumption]: teenagers use clearly
# more on Friday to Sunday, adults somewhat more at weekends.
WEEKDAY_FACTORS = {
    "adolescent": (0.85, 0.85, 0.90, 0.95, 1.10, 1.30, 1.25),
    "young_adult": (0.90, 0.92, 0.95, 0.97, 1.05, 1.15, 1.06),
    "older": (0.95, 0.97, 0.98, 1.00, 1.02, 1.05, 1.03),
}
DAY_TO_DAY_SIGMA = 0.45
ZERO_DAY_SHARE = {"adolescent": 0.04, "young_adult": 0.06, "older": 0.12}

# Relative likelihood of starting a session in each local hour (0-23),
# school/work days and weekends [assumption]. Shifted per person by their
# chronotype; nights before Saturday and Sunday shift one hour later.
HOURLY_WEIGHTS = {
    "adolescent": {
        "weekday": (3, 2, 1, .5, .3, .3, 2, 4, 1, 1, 1, 1, 2, 3, 5, 7, 8, 8, 8, 9, 10, 10, 9, 6),
        "weekend": (6, 4, 2, 1, .5, .3, .5, 1, 2, 3, 4, 5, 5, 5, 6, 6, 7, 7, 8, 9, 10, 10, 9, 8),
    },
    "young_adult": {
        "weekday": (3, 1.5, .8, .4, .3, .5, 2, 4, 4, 3, 3, 3, 5, 4, 3, 3, 4, 6, 7, 8, 9, 9, 8, 5),
        "weekend": (5, 3, 1.5, .8, .4, .3, .5, 1, 3, 4, 5, 5, 5, 5, 5, 5, 6, 7, 8, 9, 9, 9, 8, 7),
    },
    "older": {
        "weekday": (1, .5, .3, .2, .3, 1, 3, 5, 5, 4, 3, 3, 5, 4, 3, 3, 4, 6, 7, 8, 8, 6, 4, 2),
        "weekend": (1.5, .8, .4, .3, .3, .6, 2, 4, 5, 5, 5, 5, 5, 4, 4, 4, 5, 6, 7, 8, 8, 6, 4, 2.5),
    },
}
CHRONOTYPE_OFFSET_HOURS = {"adolescent": 1.0, "young_adult": 0.5, "older": -0.5}
CHRONOTYPE_SIGMA_HOURS = 1.2

# YouTube content [assumption]: share of sessions that are Shorts runs, and
# how long items are watched (seconds, log-normal median and sigma).
SHORTS_SESSION_SHARE = {"adolescent": 0.30, "young_adult": 0.20, "older": 0.08}
# Shorts runs are shorter than long-video sessions: they get this fraction of
# an average session's time (keeps both the share of Shorts time and the row
# count realistic).
SHORTS_SESSION_TIME_FACTOR = 0.5
SHORTS_WATCH_SECONDS = (35.0, 0.45)
LONG_WATCH_SECONDS = (420.0, 0.75)
# Seconds between one item ending and the next starting.
GAP_SECONDS = (2, 20)
# Other platforms: one event per item, watched/used about this long.
ITEM_SECONDS = {"tiktok": (25.0, 0.5), "instagram": (20.0, 0.6), "spotify": (200.0, 0.3), "linkedin": (60.0, 0.6)}


@dataclass(frozen=True)
class Persona:
    age_range: str
    age: int
    sex: str
    model_group: str
    # Median minutes per day per platform (0 = does not use it).
    daily_minutes: dict[str, float]
    sessions_per_day: float
    # Hours added to every session start (positive = later, night owl).
    chronotype_shift: float
    shorts_share: float

    @property
    def age_bucket(self) -> str:
        """Legacy users.age_bucket value."""
        return {"adolescent": "adolescent", "young_adult": "adult", "older": "older"}[self.model_group]

    @property
    def cohort(self) -> str:
        return f"{self.age_bucket}_{self.sex}"


def assign_demographics(rng: random.Random) -> tuple[str, int, str]:
    age_range = rng.choices(AGE_RANGES, weights=[AGE_RANGE_WEIGHTS[r] for r in AGE_RANGES], k=1)[0]
    low, high = age_bounds(age_range)
    return age_range, rng.randint(low, high), rng.choice(("female", "male"))


def generate_persona(rng: random.Random) -> Persona:
    age_range, age, sex = assign_demographics(rng)
    group = model_group(age_range)
    female_median, male_median = TOTAL_MINUTES_MEDIAN[age_range]
    total_median = female_median if sex == "female" else male_median
    # One draw for the person's overall appetite, so heavy users are heavy on
    # all their platforms; a smaller draw per platform for taste.
    appetite = math.exp(rng.gauss(0.0, PERSON_SIGMA[group]))
    tastes: dict[str, float] = {}
    for platform in PLATFORMS:
        share = PLATFORM_SHARE[group][sex][platform]
        if share > 0 and rng.random() >= NON_USER_SHARE[group][platform]:
            tastes[platform] = share * math.exp(rng.gauss(0.0, 0.35))
    if not tastes:
        tastes["youtube"] = 1.0
    # The person's total time is spread over the platforms they use, so not
    # using one shifts time to the others instead of lowering the total.
    taste_total = sum(tastes.values())
    daily_minutes = {
        platform: total_median * appetite * tastes[platform] / taste_total if platform in tastes else 0.0
        for platform in PLATFORMS
    }
    # Heavier users also open the apps more often, but less than proportionally.
    sessions = SESSIONS_PER_DAY[group] * math.exp(rng.gauss(0.0, 0.35)) * appetite ** 0.4
    return Persona(
        age_range=age_range,
        age=age,
        sex=sex,
        model_group=group,
        daily_minutes=daily_minutes,
        sessions_per_day=sessions,
        chronotype_shift=CHRONOTYPE_OFFSET_HOURS[group] + rng.gauss(0.0, CHRONOTYPE_SIGMA_HOURS),
        shorts_share=min(0.95, max(0.0, SHORTS_SESSION_SHARE[group] + rng.gauss(0.0, 0.12))),
    )


@dataclass(frozen=True)
class SyntheticItem:
    """One watched/used item, before it becomes a usage_events row."""

    platform: str
    product: str
    event_type: str
    occurred_at: datetime
    watched_seconds: int
    video_id: str | None


def generate_days(
    rng: random.Random,
    persona: Persona,
    *,
    first_day: datetime,
    total_days: int,
) -> list[SyntheticItem]:
    """Items for `total_days` days starting at midnight of `first_day` (local time as UTC)."""
    items: list[SyntheticItem] = []
    busy_until: datetime | None = None
    total_share = sum(m for m in persona.daily_minutes.values()) or 1.0
    for offset in range(total_days):
        day = first_day + timedelta(days=offset)
        weekday = day.weekday()
        if rng.random() < ZERO_DAY_SHARE[persona.model_group]:
            continue
        factor = WEEKDAY_FACTORS[persona.model_group][weekday] * math.exp(rng.gauss(0.0, DAY_TO_DAY_SIGMA))
        sessions: list[tuple[datetime, str, float]] = []
        for platform, median_minutes in persona.daily_minutes.items():
            if median_minutes <= 0:
                continue
            minutes = median_minutes * factor
            # Sessions on this platform follow its share of the person's time.
            expected = persona.sessions_per_day * (median_minutes / total_share)
            count = max(1, _poisson(rng, expected))
            weights = [rng.gammavariate(1.5, 1.0) for _ in range(count)]
            total_weight = sum(weights)
            for weight in weights:
                start = _session_start(rng, persona, day)
                sessions.append((start, platform, minutes * 60 * weight / total_weight))
        sessions.sort(key=lambda session: session[0])
        for start, platform, seconds in sessions:
            if busy_until is not None and start < busy_until:
                start = busy_until + timedelta(minutes=rng.randint(5, 40))
            produced, busy_until = _session_items(rng, persona, platform, start, seconds)
            items.extend(produced)
    return items


def _session_start(rng: random.Random, persona: Persona, day: datetime) -> datetime:
    weekday = day.weekday()
    # Friday and Saturday evenings run into the weekend's late nights.
    kind = "weekend" if weekday in (5, 6) else "weekday"
    hour = rng.choices(range(24), weights=HOURLY_WEIGHTS[persona.model_group][kind], k=1)[0]
    shift = persona.chronotype_shift + (1.0 if weekday in (4, 5) and hour >= 18 else 0.0)
    minutes = hour * 60 + rng.uniform(0, 60) + shift * 60
    # Keep the session on its own calendar day (late shifts stay before midnight
    # of the next day by wrapping into the early hours).
    minutes %= 24 * 60
    return day + timedelta(minutes=minutes)


def _session_items(
    rng: random.Random,
    persona: Persona,
    platform: str,
    start: datetime,
    budget_seconds: float,
) -> tuple[list[SyntheticItem], datetime]:
    items: list[SyntheticItem] = []
    at = start
    if platform == "youtube":
        shorts = rng.random() < persona.shorts_share
        if shorts:
            budget_seconds *= SHORTS_SESSION_TIME_FACTOR
        product, (median, sigma) = ("shorts", SHORTS_WATCH_SECONDS) if shorts else ("long", LONG_WATCH_SECONDS)
        prefix = "synthetic_youtube_short_" if shorts else "synthetic_youtube_long_"
        event_type = "watch"
    else:
        product = {"tiktok": "shorts", "instagram": "feed", "spotify": "audio", "linkedin": "feed"}[platform]
        median, sigma = ITEM_SECONDS[platform]
        prefix = f"synthetic_{platform}_" if platform == "tiktok" else None
        event_type = {"tiktok": "watch", "instagram": "video_watch", "spotify": "listen", "linkedin": "activity"}[platform]
    remaining = max(budget_seconds, 15.0)
    while remaining > 0:
        watched = max(5, int(min(remaining, median * math.exp(rng.gauss(0.0, sigma)))))
        items.append(
            SyntheticItem(
                platform=platform,
                product=product,
                event_type=event_type,
                occurred_at=at,
                watched_seconds=watched,
                video_id=f"{prefix}{rng.randint(10000, 99999)}" if prefix else None,
            )
        )
        remaining -= watched
        at += timedelta(seconds=watched + rng.randint(*GAP_SECONDS))
    return items, at


def _poisson(rng: random.Random, mean: float) -> int:
    if mean <= 0:
        return 0
    limit, count, product = math.exp(-mean), 0, rng.random()
    while product > limit:
        count += 1
        product *= rng.random()
    return count
