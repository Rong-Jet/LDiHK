import math
import logging

# Set up basic logging to catch bad synthetic data without crashing the server
logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')

# ==========================================
# 1. THE CLINICAL AOR DATABASE 
# ==========================================
AOR_DB = {
    "adolescent": {
        "age": {"11-13": 1.00, "14-16": 1.50, "17-18": 1.20},
        "sex": {"Male": 1.00, "Female": 1.40},
        "time": {"0-1h": 1.00, "1-3h": 1.13, "3-5h": 1.60, "5h+": 2.65},
        "frequency": {"Low": 1.00, "Medium": 1.15, "High": 1.30, "Extreme": 1.50},
        "content_format": {"Active Messaging": 0.80, "Passive Scrolling": 1.00, "Short-form": 1.80}
    },
    "young_adult": {
        "age": {"19-23": 1.00, "24-26": 2.04, "27+": 1.38},
        "sex": {"Female": 1.00, "Male": 0.79},
        "time": {"0-30m": 1.00, "31-60m": 0.95, "61-120m": 1.32, "121m+": 1.20},
        "frequency": {"Low": 1.00, "Medium": 1.35, "High": 1.80, "Extreme": 2.74},
        "platforms": {"0-2": 1.00, "3-4": 1.57, "5-6": 2.16, "7-11": 3.08},
        "content_format": {"Long-form": 1.00, "Text": 1.25, "Short-form": 1.60}
    },
    "older_adult": {
        "age": {"30-45": 1.00, "46-60": 0.90, "60+": 0.85},
        "sex": {"Female": 1.00, "Male": 0.95},
        "time": {"0-1h": 1.00, "1-2h": 0.95, "2-3h": 1.10, "3h+": 1.25},
        "platforms": {"1-2": 1.00, "3-4": 1.20, "5+": 1.50},
        "content_format": {"Community/Groups": 0.75, "Passive Newsfeed": 1.40, "Short-form": 1.20}
    }
}

# ==========================================
# 2. NUMERICAL MAPPING HELPER
# ==========================================
def map_raw_frequency_to_category(raw_visits_per_week):
    """
    Maps a continuous numerical visit count (e.g., from an API or screen time data)
    to the clinical quartiles defined by the epidemiological literature.
    """
    try:
        visits = int(raw_visits_per_week)
        if visits <= 8:
            return "Low"
        elif visits <= 30:
            return "Medium"
        elif visits <= 57:
            return "High"
        else:
            return "Extreme"
    except (ValueError, TypeError):
        # Fallback to Medium risk if the data is corrupted or missing
        logging.warning(f"Corrupted frequency data: '{raw_visits_per_week}'. Defaulting to 'Medium'.")
        return "Medium"

# ==========================================
# 3. THE CORE ENGINE
# ==========================================
class PhenotypeRiskEngine:
    def __init__(self):
        # Baseline intercepts (Beta_0) representing log-odds before behavioral multipliers
        self.intercepts = {'adolescent': -2.0, 'young_adult': -2.0, 'older_adult': -2.2}

    def _calculate_probability(self, base_log_odds, aor_list):
        total_log_odds = base_log_odds + sum(math.log(aor) for aor in aor_list)
        probability = 1 / (1 + math.exp(-total_log_odds))
        return round(probability * 100, 2)

    def score_adolescent(self, age, sex, time, freq, content_format):
        return self._calculate_probability(self.intercepts['adolescent'], [age, sex, time, freq, content_format])

    def score_young_adult(self, age, sex, time, freq, plat, content_format):
        return self._calculate_probability(self.intercepts['young_adult'], [age, sex, time, freq, plat, content_format])

    def score_older_adult(self, age, sex, time, plat, content_format):
        return self._calculate_probability(self.intercepts['older_adult'], [age, sex, time, plat, content_format])

# ==========================================
# 4. THE "GLUE" PROCESSOR (Data Pipeline)
# ==========================================
def process_user_profile(user_data):
    """
    Safely maps dictionary data (strings/ints) to AOR floats and calculates the score.
    Returns None if the essential data is missing or fully corrupted.
    """
    engine = PhenotypeRiskEngine()
    cohort = user_data.get("demographic_cohort")
    
    if cohort not in AOR_DB:
        logging.warning(f"Invalid cohort '{cohort}' found in profile data.")
        return None

    try:
        if cohort == "adolescent":
            # Map raw numerical frequency to string quartile if provided
            freq_key = map_raw_frequency_to_category(user_data["raw_frequency"]) if "raw_frequency" in user_data else user_data["frequency"]
            
            aors = [
                AOR_DB[cohort]["age"][user_data["age"]],
                AOR_DB[cohort]["sex"][user_data["sex"]],
                AOR_DB[cohort]["time"][user_data["time"]],
                AOR_DB[cohort]["frequency"][freq_key],
                AOR_DB[cohort]["content_format"][user_data["content_format"]]
            ]
            return engine.score_adolescent(*aors)
            
        elif cohort == "young_adult":
            freq_key = map_raw_frequency_to_category(user_data["raw_frequency"]) if "raw_frequency" in user_data else user_data["frequency"]
            
            aors = [
                AOR_DB[cohort]["age"][user_data["age"]],
                AOR_DB[cohort]["sex"][user_data["sex"]],
                AOR_DB[cohort]["time"][user_data["time"]],
                AOR_DB[cohort]["frequency"][freq_key],
                AOR_DB[cohort]["platforms"][user_data["platforms"]],
                AOR_DB[cohort]["content_format"][user_data["content_format"]]
            ]
            return engine.score_young_adult(*aors)
            
        elif cohort == "older_adult":
            # Older adults do not use frequency in this specific model
            aors = [
                AOR_DB[cohort]["age"][user_data["age"]],
                AOR_DB[cohort]["sex"][user_data["sex"]],
                AOR_DB[cohort]["time"][user_data["time"]],
                AOR_DB[cohort]["platforms"][user_data["platforms"]],
                AOR_DB[cohort]["content_format"][user_data["content_format"]]
            ]
            return engine.score_older_adult(*aors)

    except KeyError as e:
        # Prevents a complete crash if the generator provides "120m" instead of "121m+"
        logging.warning(f"Data mismatch for user: Key {str(e)} was not found in the AOR database.")
        return None

# ==========================================
# 5. DEMONSTRATION SCRIPT
# ==========================================
if __name__ == "__main__":
    
    # Simulating a user profile ingested with a continuous numeric frequency (45 visits/week)
    user_with_numerical_data = {
        "demographic_cohort": "young_adult",
        "age": "24-26",
        "sex": "Male",
        "time": "121m+",
        "raw_frequency": 45,  # The script will dynamically map this to "High"
        "platforms": "7-11",
        "content_format": "Short-form"
    }
    
    # Simulating a user using the old categorical format to prove backwards compatibility
    user_with_categorical_data = {
        "demographic_cohort": "adolescent",
        "age": "14-16",
        "sex": "Female",
        "time": "5h+",
        "frequency": "Extreme",
        "content_format": "Short-form"
    }

    # Process Profiles
    score_one = process_user_profile(user_with_numerical_data)
    score_two = process_user_profile(user_with_categorical_data)
    
    print("--- MVP RISK ENGINE TEST RESULTS ---")
    print(f"Profile 1 (Young Adult, 45 visits/wk): {score_one}% Risk Score")
    print(f"Profile 2 (Adolescent, Extreme Categorical): {score_two}% Risk Score")