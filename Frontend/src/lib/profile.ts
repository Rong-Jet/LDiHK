import type { ComparisonGroup, UserProfile } from './api';

/** Same 5-year ranges as backend/demographics.py. */
export const AGE_RANGES = [
  '13-14', '15-19', '20-24', '25-29', '30-34', '35-39', '40-44',
  '45-49', '50-54', '55-59', '60-64', '65-69', '70+',
] as const;

export const SEX_OPTIONS: { value: string; label: string }[] = [
  { value: 'female', label: 'Female' },
  { value: 'male', label: 'Male' },
  { value: 'diverse', label: 'Diverse' },
];

/** Value used by the selects for "no answer". */
export const NO_ANSWER = '';

export const EMPTY_PROFILE: UserProfile = { age_range: null, sex: null };

export function hasProfile(profile: UserProfile | undefined | null): boolean {
  return !!profile && (!!profile.age_range || !!profile.sex);
}

export function formatAgeRange(range: string): string {
  return range.endsWith('+') ? `${range.slice(0, -1)} and older` : `${range.replace('-', '–')}`;
}

/** "women aged 15–29 (48 people)" / "everyone (1,512 people)". */
export function describeComparisonGroup(group: ComparisonGroup | undefined | null): string | null {
  if (!group) return null;
  const people = `${group.size.toLocaleString()} ${group.size === 1 ? 'person' : 'people'}`;
  if (group.basis === 'everyone') return `everyone (${people})`;
  const who = group.sex === 'female' ? 'women' : group.sex === 'male' ? 'men' : 'people';
  if (!group.ageRanges) return `${who} (${people})`;
  const [first, last] = group.ageRanges;
  const low = first.split('-')[0].replace('+', '');
  const age = last.endsWith('+') ? `${low} and older` : `${low}–${last.split('-')[1]}`;
  return `${who} aged ${age} (${people})`;
}
