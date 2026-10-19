import React, { useEffect, useState } from 'react';
import { Check, UserRound } from 'lucide-react';
import { describeApiError, type ComparisonGroup, type UserProfile } from '../lib/api';
import { AGE_RANGES, NO_ANSWER, SEX_OPTIONS, describeComparisonGroup, formatAgeRange } from '../lib/profile';

const SELECT_CLASS =
  'w-full bg-white border border-brand-navy/20 rounded-xl px-3 py-2 text-xs font-semibold text-brand-navy focus:outline-none focus:ring-2 focus:ring-brand-teal/30 focus:border-brand-teal disabled:opacity-60';

/** Age range and sex selects; both optional ("Prefer not to say"). */
export function ProfileFields({
  value,
  onChange,
  disabled = false,
  idPrefix,
}: {
  value: UserProfile;
  onChange: (value: UserProfile) => void;
  disabled?: boolean;
  idPrefix: string;
}) {
  return (
    <div className="grid grid-cols-2 gap-3 text-left">
      <label className="block space-y-1" htmlFor={`${idPrefix}-age`}>
        <span className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/50 block">Age range</span>
        <select
          id={`${idPrefix}-age`}
          className={SELECT_CLASS}
          value={value.age_range ?? NO_ANSWER}
          disabled={disabled}
          onChange={(event) => onChange({ ...value, age_range: event.target.value || null })}
        >
          <option value={NO_ANSWER}>Prefer not to say</option>
          {AGE_RANGES.map((range) => (
            <option key={range} value={range}>{formatAgeRange(range)}</option>
          ))}
        </select>
      </label>
      <label className="block space-y-1" htmlFor={`${idPrefix}-sex`}>
        <span className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/50 block">Sex</span>
        <select
          id={`${idPrefix}-sex`}
          className={SELECT_CLASS}
          value={value.sex ?? NO_ANSWER}
          disabled={disabled}
          onChange={(event) => onChange({ ...value, sex: event.target.value || null })}
        >
          <option value={NO_ANSWER}>Prefer not to say</option>
          {SEX_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </label>
    </div>
  );
}

/**
 * Editable profile on the console tabs. Shows whom the user is currently
 * compared with, and why giving age and sex makes that comparison fairer.
 */
export function ProfileCard({
  profile,
  onSave,
  comparisonGroup,
}: {
  profile: UserProfile;
  onSave: (profile: UserProfile) => Promise<unknown>;
  comparisonGroup?: ComparisonGroup | null;
}) {
  const [draft, setDraft] = useState<UserProfile>(profile);
  const [state, setState] = useState<{ pending: boolean; saved: boolean; error: string | null }>({ pending: false, saved: false, error: null });

  useEffect(() => {
    setDraft(profile);
  }, [profile.age_range, profile.sex]);

  const changed = draft.age_range !== profile.age_range || draft.sex !== profile.sex;
  const compared = describeComparisonGroup(comparisonGroup);

  const save = async () => {
    setState({ pending: true, saved: false, error: null });
    try {
      await onSave(draft);
      setState({ pending: false, saved: true, error: null });
    } catch (error) {
      setState({ pending: false, saved: false, error: describeApiError(error, 'Saving failed. Please retry.') });
    }
  };

  return (
    <div className="mb-6 bg-white border border-brand-navy/10 rounded-2xl p-4 flex flex-col md:flex-row md:items-end gap-4 text-left">
      <div className="flex items-start gap-3 md:w-1/3">
        <div className="w-9 h-9 rounded-xl bg-brand-teal/10 flex items-center justify-center text-brand-teal shrink-0">
          <UserRound className="w-4 h-4" />
        </div>
        <div className="text-xs leading-relaxed">
          <span className="font-extrabold text-brand-navy block">Compare with people like you</span>
          <span className="text-brand-navy/60">
            Optional. Usage differs a lot by age and sex, so we compare you with your own group.
            {compared ? <> Currently compared with <strong className="text-brand-navy">{compared}</strong>.</> : null}
          </span>
        </div>
      </div>
      <div className="flex-grow">
        <ProfileFields value={draft} onChange={(next) => { setDraft(next); setState((s) => ({ ...s, saved: false })); }} disabled={state.pending} idPrefix="profile-card" />
      </div>
      <div className="flex flex-col items-start md:items-end gap-1 shrink-0">
        <button
          onClick={save}
          disabled={!changed || state.pending}
          className="px-4 py-2 rounded-xl bg-brand-navy text-white text-xs font-bold cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {state.pending ? 'Saving…' : 'Save'}
        </button>
        {state.saved && !changed && (
          <span className="text-[10px] font-bold text-brand-teal flex items-center gap-1"><Check className="w-3 h-3" /> Saved</span>
        )}
        {state.error && <span className="text-[10px] font-bold text-brand-peach" role="alert">{state.error}</span>}
      </div>
    </div>
  );
}
