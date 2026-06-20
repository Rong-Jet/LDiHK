import math
import logging

# Set up basic logging to catch bad synthetic data without crashing
logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')

# ==========================================
# 1. THE CLINICAL AOR DATABASE (Standardized Keys)
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
# 2. THE CORE ENGINE
# ==========================================
class PhenotypeRiskEngine:
    def __init__(self):
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
# 3. THE "GLUE" PROCESSOR (Hardened)
# ==========================================
def process_user_profile(user_data):
    """
    Safely maps string data to AOR floats and calculates the score.
    Returns None if the data is corrupted or missing keys.
    """
    engine = PhenotypeRiskEngine()
    cohort = user_data.get("demographic_cohort")
    
    if cohort not in AOR_DB:
        logging.warning(f"Invalid cohort '{cohort}' found in profile data.")
        return None

    try:
        if cohort == "adolescent":
            aors = [
                AOR_DB[cohort]["age"][user_data["age"]],
                AOR_DB[cohort]["sex"][user_data["sex"]],
                AOR_DB[cohort]["time"][user_data["time"]],
                AOR_DB[cohort]["frequency"][user_data["frequency"]],
                AOR_DB[cohort]["content_format"][user_data["content_format"]]
            ]
            return engine.score_adolescent(*aors)
            
        elif cohort == "young_adult":
            aors = [
                AOR_DB[cohort]["age"][user_data["age"]],
                AOR_DB[cohort]["sex"][user_data["sex"]],
                AOR_DB[cohort]["time"][user_data["time"]],
                AOR_DB[cohort]["frequency"][user_data["frequency"]],
                AOR_DB[cohort]["platforms"][user_data["platforms"]],
                AOR_DB[cohort]["content_format"][user_data["content_format"]]
            ]
            return engine.score_young_adult(*aors)
            
        elif cohort == "older_adult":
            aors = [
                AOR_DB[cohort]["age"][user_data["age"]],
                AOR_DB[cohort]["sex"][user_data["sex"]],
                AOR_DB[cohort]["time"][user_data["time"]],
                AOR_DB[cohort]["platforms"][user_data["platforms"]],
                AOR_DB[cohort]["content_format"][user_data["content_format"]]
            ]
            return engine.score_older_adult(*aors)

    except KeyError as e:
        # If the synthetic DB passes "120m" instead of "121m+", this catches it safely
        logging.warning(f"Data mismatch: The value {str(e)} was not found in the AOR database.")
        return None

# ==========================================
# DEMO TEST
# ==========================================
if __name__ == "__main__":
    
    # Clean profile
    synthetic_user_row = {
        "demographic_cohort": "young_adult",
        "age": "24-26",
        "sex": "Male",
        "time": "121m+",
        "frequency": "Extreme",
        "platforms": "7-11",
        "content_format": "Short-form"
    }

    final_score = process_user_profile(synthetic_user_row)
    print(f"Calculated Risk Score: {final_score}%")