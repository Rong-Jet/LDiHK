import type { RiskReferenceMetrics, UserProfile } from './api';

/**
 * Risk score model: logistic function of daily watch volume, fragmentation
 * and late-night use.
 *
 *   z = intercept + volume * hours + fragmentation * index + lateNight * hours
 *   score = 1 / (1 + e^-z)
 *
 * One coefficient set per model group (adolescents, young adults, older), each
 * optionally split by sex. Until validated per-group coefficients exist all of
 * them equal the initial model, so the formula is the same for everyone.
 * Replace the entries in RISK_MODELS to add custom coefficients; nothing else
 * needs to change.
 *
 * Age and sex already matter through the comparison: each input is measured
 * relative to the user's cohort (people of similar age range and sex). A user
 * exactly at their cohort's typical value scores like a user at the overall
 * typical value, so a group that typically uses more (e.g. adolescents) is not
 * scored higher for that alone, while a user far above their own group is.
 */

export type ModelGroup = 'adolescent' | 'young_adult' | 'older';

export interface RiskCoefficients {
  intercept: number;
  /** Per hour of watching per active day. */
  volume: number;
  /** Per unit of fragmentation (share of the day's hours with use, 0-1). */
  fragmentation: number;
  /** Per hour of watching between 23:00 and 04:59. */
  lateNight: number;
}

/** The initial model (unchanged from the first version of the risk tab). */
export const INITIAL_COEFFICIENTS: RiskCoefficients = {
  intercept: -2.1,
  volume: 0.35,
  fragmentation: 0.8,
  lateNight: 1.2,
};

type SexKey = 'female' | 'male';

/** Per model group: `default`, optionally overridden for `female` / `male`. */
export const RISK_MODELS: Record<ModelGroup, { default: RiskCoefficients } & Partial<Record<SexKey, RiskCoefficients>>> = {
  adolescent: { default: INITIAL_COEFFICIENTS },
  young_adult: { default: INITIAL_COEFFICIENTS },
  older: { default: INITIAL_COEFFICIENTS },
};

/** Same grouping as backend/demographics.py. */
export function modelGroupFor(ageRange: string | null | undefined): ModelGroup | null {
  if (!ageRange) return null;
  if (ageRange === '13-14' || ageRange === '15-19') return 'adolescent';
  if (ageRange === '20-24' || ageRange === '25-29' || ageRange === '30-34') return 'young_adult';
  return 'older';
}

export function coefficientsFor(profile: UserProfile | null | undefined): RiskCoefficients {
  const group = modelGroupFor(profile?.age_range);
  if (!group) return INITIAL_COEFFICIENTS;
  const models = RISK_MODELS[group];
  const sex = profile?.sex === 'female' || profile?.sex === 'male' ? profile.sex : null;
  return (sex && models[sex]) || models.default;
}

export interface DayInputs {
  /** Watch hours that day. */
  hours: number;
  lateNightHours: number;
  /** Share of the day's hours with at least 5 minutes of watching (0-1). */
  fragmentation: number;
}

export interface CohortReference {
  cohort: RiskReferenceMetrics;
  overall: RiskReferenceMetrics;
}

/** The day's inputs moved by how far the cohort's typical value is from everyone's. */
export function cohortAdjusted(inputs: DayInputs, reference: CohortReference | null): DayInputs {
  if (!reference) return inputs;
  const shift = (value: number, cohort: number, overall: number) => Math.max(0, value - cohort + overall);
  return {
    hours: shift(inputs.hours, reference.cohort.dailyHours, reference.overall.dailyHours),
    lateNightHours: shift(inputs.lateNightHours, reference.cohort.lateNightHours, reference.overall.lateNightHours),
    fragmentation: Math.min(1, shift(inputs.fragmentation, reference.cohort.fragmentation, reference.overall.fragmentation)),
  };
}

/** Risk score in percent (0-100). */
export function riskScore(inputs: DayInputs, coefficients: RiskCoefficients, reference: CohortReference | null = null): number {
  const x = cohortAdjusted(inputs, reference);
  const z = coefficients.intercept
    + coefficients.volume * x.hours
    + coefficients.fragmentation * x.fragmentation
    + coefficients.lateNight * x.lateNightHours;
  return 100 / (1 + Math.exp(-z));
}
