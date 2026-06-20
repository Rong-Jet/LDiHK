import numpy as np
import pandas as pd
import uuid
from datetime import datetime, timedelta, timezone
import random
import hashlib
import os

# ==========================================
# 1. DEMOGRAPHIC & PROBABILITY MATRICES
# ==========================================
def normalize_weights(weights):
    return [w / sum(weights) for w in weights]

PLATFORM_WEIGHTS = {
    'TikTok': normalize_weights([0.05, 0.04, 0.02, 0.01, 0.01, 0.01, 0.02, 0.03, 0.03, 0.03, 0.04, 0.04, 0.05, 0.05, 0.06, 0.07, 0.08, 0.08, 0.09, 0.10, 0.10, 0.10, 0.09, 0.08]),
    'Instagram': normalize_weights([0.02, 0.01, 0.01, 0.01, 0.01, 0.02, 0.03, 0.05, 0.07, 0.08, 0.08, 0.09, 0.10, 0.09, 0.08, 0.07, 0.06, 0.07, 0.08, 0.08, 0.07, 0.06, 0.05, 0.04]),
    'YouTube_Shorts': normalize_weights([0.02, 0.01, 0.01, 0.01, 0.01, 0.02, 0.04, 0.06, 0.06, 0.05, 0.05, 0.05, 0.06, 0.06, 0.07, 0.08, 0.09, 0.10, 0.10, 0.09, 0.08, 0.06, 0.05, 0.04]),
    'YouTube_Long': normalize_weights([0.03, 0.02, 0.01, 0.01, 0.01, 0.01, 0.02, 0.03, 0.04, 0.03, 0.03, 0.04, 0.04, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12, 0.14, 0.14, 0.12, 0.09, 0.06]),
    'Spotify': normalize_weights([0.02, 0.01, 0.01, 0.01, 0.01, 0.02, 0.04, 0.08, 0.10, 0.09, 0.08, 0.07, 0.07, 0.07, 0.07, 0.08, 0.09, 0.09, 0.06, 0.05, 0.04, 0.03, 0.03, 0.03]),
    'LinkedIn': normalize_weights([0.005, 0.005, 0.005, 0.005, 0.005, 0.01, 0.03, 0.06, 0.10, 0.12, 0.12, 0.10, 0.08, 0.08, 0.10, 0.08, 0.06, 0.05, 0.04, 0.03, 0.02, 0.01, 0.01, 0.01])
}

AFFINITY_MATRIX = {
    'Adolescent_Female': {'TikTok': 0.95, 'Instagram': 0.90, 'Spotify': 0.85, 'YouTube_Shorts': 0.70, 'YouTube_Long': 0.60, 'LinkedIn': 0.00},
    'Adolescent_Male':   {'TikTok': 0.75, 'Instagram': 0.60, 'Spotify': 0.80, 'YouTube_Shorts': 0.90, 'YouTube_Long': 0.95, 'LinkedIn': 0.00},
    'Adult_Female':      {'TikTok': 0.55, 'Instagram': 0.80, 'Spotify': 0.75, 'YouTube_Shorts': 0.50, 'YouTube_Long': 0.65, 'LinkedIn': 0.55},
    'Adult_Male':        {'TikTok': 0.40, 'Instagram': 0.65, 'Spotify': 0.70, 'YouTube_Shorts': 0.60, 'YouTube_Long': 0.85, 'LinkedIn': 0.65},
    'Older_Female':      {'TikTok': 0.15, 'Instagram': 0.55, 'Spotify': 0.35, 'YouTube_Shorts': 0.20, 'YouTube_Long': 0.75, 'LinkedIn': 0.30},
    'Older_Male':        {'TikTok': 0.10, 'Instagram': 0.35, 'Spotify': 0.30, 'YouTube_Shorts': 0.20, 'YouTube_Long': 0.85, 'LinkedIn': 0.45},
}

# ==========================================
# 2. THE PERSONA ENGINE 
# ==========================================
def assign_demographics():
    sex = random.choice(['Male', 'Female'])
    age_group_roll = random.random()
    if age_group_roll < 0.20: age, cohort = random.randint(13, 17), f"Adolescent_{sex}"
    elif age_group_roll < 0.80: age, cohort = random.randint(18, 49), f"Adult_{sex}"
    else: age, cohort = random.randint(50, 75), f"Older_{sex}"
    return age, sex, cohort

def generate_user_persona():
    age, sex, cohort = assign_demographics()
    all_platforms = ['TikTok', 'Instagram', 'YouTube_Shorts', 'YouTube_Long', 'Spotify', 'LinkedIn']
    active_platforms = [p for p in all_platforms if random.random() < AFFINITY_MATRIX[cohort][p]]
    if not active_platforms: active_platforms = ['YouTube_Long']
    
    persona = {
        'age': age,
        'sex': sex,
        'cohort': cohort,
        'platforms': active_platforms,
        'avg_daily_sessions': {},
        'usual_times_of_activity': {}
    }
    
    for p in active_platforms:
        base = 1
        
        if cohort == 'Adolescent_Female':
            if p == 'TikTok': base = 15
            elif p == 'Instagram': base = 15
            elif p == 'YouTube_Shorts': base = 10
            elif p == 'YouTube_Long': base = 2
            elif p == 'Spotify': base = 5
            
        elif cohort == 'Adolescent_Male':
            if p == 'TikTok': base = 10
            elif p == 'Instagram': base = 8
            elif p == 'YouTube_Shorts': base = 12
            elif p == 'YouTube_Long': base = 5
            elif p == 'Spotify': base = 5
            
        elif cohort == 'Adult_Female':
            if p == 'TikTok': base = 8
            elif p == 'Instagram': base = 12
            elif p == 'YouTube_Shorts': base = 5
            elif p == 'YouTube_Long': base = 3
            elif p == 'Spotify': base = 6
            elif p == 'LinkedIn': base = 2
            
        elif cohort == 'Adult_Male':
            if p == 'TikTok': base = 6
            elif p == 'Instagram': base = 8
            elif p == 'YouTube_Shorts': base = 6
            elif p == 'YouTube_Long': base = 4
            elif p == 'Spotify': base = 6
            elif p == 'LinkedIn': base = 3
            
        elif cohort == 'Older_Female':
            if p == 'TikTok': base = 2
            elif p == 'Instagram': base = 6
            elif p == 'YouTube_Shorts': base = 2
            elif p == 'YouTube_Long': base = 4
            elif p == 'Spotify': base = 3
            elif p == 'LinkedIn': base = 1
            
        elif cohort == 'Older_Male':
            if p == 'TikTok': base = 1
            elif p == 'Instagram': base = 3
            elif p == 'YouTube_Shorts': base = 2
            elif p == 'YouTube_Long': base = 5
            elif p == 'Spotify': base = 3
            elif p == 'LinkedIn': base = 2
            
        persona['avg_daily_sessions'][p] = max(1, int(random.gauss(base, base * 0.25)))
        
        num_usual_times = random.choice([1, 2, 3])
        if 'Adolescent' in cohort: 
            valid_hours = [7, 15, 16, 17, 20, 21, 22, 23] 
        elif 'Adult' in cohort: 
            valid_hours = [7, 8, 12, 17, 18, 20, 21, 22] 
        elif 'Older' in cohort: 
            valid_hours = [6, 7, 8, 12, 18, 19, 20] 
            
        persona['usual_times_of_activity'][p] = np.random.choice(valid_hours, size=num_usual_times).tolist()
        
    return persona

# ==========================================
# 3. CHRONOLOGICAL EVENT GENERATOR 
# ==========================================
def generate_user_telemetry(user_id, import_id, total_days, base_date, persona):
    events = []
    carryover_time = None 
    
    for day_offset in range(total_days):
        current_day = base_date - timedelta(days=total_days - day_offset)
        is_weekend = current_day.weekday() >= 5
        
        if is_weekend:
            if 'Adolescent' in persona['cohort']: weekend_mod = 1.6
            elif 'Older' in persona['cohort']: weekend_mod = 1.1
            else: weekend_mod = 1.3
        else:
            weekend_mod = 1.0
            
        todays_raw_events = []
        
        for platform in persona['platforms']:
            if platform == 'LinkedIn' and is_weekend: continue
                
            daily_variance = random.gauss(0, persona['avg_daily_sessions'][platform] * 0.15)
            sessions = max(0, int((persona['avg_daily_sessions'][platform] + daily_variance) * weekend_mod))
            
            for _ in range(sessions):
                if random.random() < 0.80: 
                    chosen_time = random.choice(persona['usual_times_of_activity'][platform])
                    base_ts = current_day.replace(hour=chosen_time, minute=0, second=0, microsecond=0)
                    blur_minutes = random.gauss(0, 45) 
                    ts = base_ts + timedelta(minutes=blur_minutes, seconds=random.randint(-30, 30))
                else:
                    hour = np.random.choice(range(24), p=PLATFORM_WEIGHTS[platform])
                    ts = current_day.replace(hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59), microsecond=0)
                    
                todays_raw_events.append({'platform': platform, 'ts': ts})
                
        todays_raw_events.sort(key=lambda x: x['ts'])
        
        for idx, ev in enumerate(todays_raw_events):
            min_gap = timedelta(minutes=random.randint(5, 15))
            if idx == 0:
                if carryover_time and ev['ts'] < carryover_time + min_gap:
                    ev['ts'] = carryover_time + min_gap
            else:
                prev_ts = todays_raw_events[idx - 1]['ts']
                if ev['ts'] < prev_ts + min_gap:
                    ev['ts'] = prev_ts + min_gap
                    
        if todays_raw_events: carryover_time = todays_raw_events[-1]['ts']
                
        for ev in todays_raw_events:
            db_platform = ev['platform'].split('_')[0] 
            product_type = 'Shorts' if 'Shorts' in ev['platform'] else 'Audio' if ev['platform'] == 'Spotify' else 'Feed'
            fingerprint = hashlib.md5(f"{user_id}_{ev['ts'].timestamp()}_{random.randint(0,1000)}".encode()).hexdigest()
            
            events.append({
                'id': str(uuid.uuid4()),
                'user_id': user_id,
                'import_id': import_id,
                'source_file_id': None,
                'platform': db_platform,
                'product': product_type,
                'event_type': 'watch' if db_platform != 'Spotify' else 'listen',
                'occurred_at': ev['ts'].isoformat(),
                'video_id': f"vid_{random.randint(10000, 99999)}",
                'event_fingerprint': fingerprint,
                'created_at': base_date.isoformat()
            })
                
    return events

# ==========================================
# 4. PIPELINE MANAGER
# ==========================================
def run_large_scale_seeder(total_profiles, total_days=1825):
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    
    users_file, imports_file, events_file = "seed_users.csv", "seed_imports.csv", "seed_usage_events.csv"
    for f in [users_file, imports_file, events_file]:
        if os.path.exists(f): os.remove(f)
            
    print(f"Starting Research-Backed Pipeline: {total_profiles} Clankers over {total_days} days.")
    
    for i in range(total_profiles):
        clanker_number = i + 1
        user_id = str(uuid.uuid4())
        import_id = str(uuid.uuid4())
        
        persona = generate_user_persona()
        
        user_row = pd.DataFrame([{
            'id': user_id,
            'external_id': f"Clanker {clanker_number} {persona['sex']} {persona['age']}",
            'created_at': (now - timedelta(days=total_days + 1)).isoformat()
        }])
        
        user_events = generate_user_telemetry(user_id, import_id, total_days, now, persona)
        
        import_row = pd.DataFrame([{
            'id': import_id,
            'user_id': user_id,
            's3_bucket': 'hackathon-gdpr-uploads',
            's3_key': f"uploads/Clanker_{clanker_number}/takeout.zip",
            'status': 'COMPLETED',
            'records_seen': len(user_events),
            'records_imported': len(user_events),
            'created_at': now.isoformat()
        }])
        
        events_df = pd.DataFrame(user_events)
        
        user_row.to_csv(users_file, mode='a', header=not os.path.exists(users_file), index=False)
        import_row.to_csv(imports_file, mode='a', header=not os.path.exists(imports_file), index=False)
        if not events_df.empty:
            events_df.to_csv(events_file, mode='a', header=not os.path.exists(events_file), index=False)
        
        print(f"Progress: Clanker {clanker_number}/{total_profiles} generated -> {len(user_events)} events.")

if __name__ == "__main__":
    run_large_scale_seeder(total_profiles=5, total_days=14)