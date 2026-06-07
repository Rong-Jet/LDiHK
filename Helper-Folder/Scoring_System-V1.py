import math

# ==========================================
# 1. THE CLINICAL AOR DATABASE
# ==========================================
# This dictionary stores all the peer-reviewed Adjusted Odds Ratios 
# mapped to their specific demographic and behavioral categories.

AOR_DB = {
    "adolescent": {
        "age": {"11-13": 1.00, "14-16": 1.50, "17-18": 1.20},
        "sex": {"Male": 1.00, "Female": 1.40},
        "time": {"0-1h": 1.00, "1-3h": 1.13, "3-5h": 1.60, "5h+": 2.65},
        "frequency": {"Low": 1.00, "Medium": 1.15, "High": 1.30, "Extreme": 1.50},
        "format": {"Active Messaging": 0.80, "Passive Scrolling": 1.00, "Short-form Video": 1.80}
    },
    "young_adult": {
        "age": {"19-23": 1.00, "24-26": 2.04, "27+": 1.38},
        "sex": {"Female": 1.00, "Male": 0.79},
        "time": {"0-30m": 1.00, "31-60m": 0.95, "61-120m": 1.32, "121m+": 1.20},
        "frequency": {"Low": 1.00, "Medium": 1.35, "High": 1.80, "Extreme": 2.74},
        "platforms": {"0-2": 1.00, "3-4": 1.57, "5-6": 2.16, "7-11": 3.08},
        "format": {"Long-form": 1.00, "Text": 1.25, "Short-form": 1.60}
    },
    "older_adult": {
        "age": {"30-45": 1.00, "46-60": 0.90, "60+": 0.85},
        "sex": {"Female": 1.00, "Male": 0.95},
        "time": {"0-1h": 1.00, "1-2h": 0.95, "2-3h": 1.10, "3h+": 1.25},
        "platforms": {"1-2": 1.00, "3-4": 1.20, "5+": 1.50},
        "format": {"Community/Groups": 0.75, "Passive Newsfeed": 1.40, "Short-form": 1.20}
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

    def score_adolescent(self, age, sex, time, freq, format):
        return self._calculate_probability(self.intercepts['adolescent'], [age, sex, time, freq, format])

    def score_young_adult(self, age, sex, time, freq, plat, format):
        return self._calculate_probability(self.intercepts['young_adult'], [age, sex, time, freq, plat, format])

    def score_older_adult(self, age, sex, time, plat, format):
        return self._calculate_probability(self.intercepts['older_adult'], [age, sex, time, plat, format])

# ==========================================
# 3. THE "GLUE" PROCESSOR
# ==========================================
def process_user_profile(user_data):
    """
    Takes a raw user dictionary (like a row from your synthetic DB), 
    looks up their specific AORs in the database, and returns their risk score.
    """
    engine = PhenotypeRiskEngine()
    cohort = user_data.get("demographic_cohort")
    
    if cohort == "adolescent":
        # Map raw strings to AOR floats
        aors = [
            AOR_DB[cohort]["age"][user_data["age"]],
            AOR_DB[cohort]["sex"][user_data["sex"]],
            AOR_DB[cohort]["time"][user_data["time"]],
            AOR_DB[cohort]["frequency"][user_data["frequency"]],
            AOR_DB[cohort]["format"][user_data["format"]]
        ]
        return engine.score_adolescent(*aors)
        
    elif cohort == "young_adult":
        aors = [
            AOR_DB[cohort]["age"][user_data["age"]],
            AOR_DB[cohort]["sex"][user_data["sex"]],
            AOR_DB[cohort]["time"][user_data["time"]],
            AOR_DB[cohort]["frequency"][user_data["frequency"]],
            AOR_DB[cohort]["platforms"][user_data["platforms"]],
            AOR_DB[cohort]["format"][user_data["format"]]
        ]
        return engine.score_young_adult(*aors)
        
    elif cohort == "older_adult":
        aors = [
            AOR_DB[cohort]["age"][user_data["age"]],
            AOR_DB[cohort]["sex"][user_data["sex"]],
            AOR_DB[cohort]["time"][user_data["time"]],
            AOR_DB[cohort]["platforms"][user_data["platforms"]],
            AOR_DB[cohort]["format"][user_data["format"]]
        ]
        return engine.score_older_adult(*aors)
    else:
        raise ValueError("Invalid demographic cohort")

# ==========================================
# DEMO TEST
# ==========================================
if __name__ == "__main__":
    
    # Imagine this is a profile pulled straight from your synthetic database
    synthetic_user_row = {
        "demographic_cohort": "young_adult",
        "age": "24-26",
        "sex": "Male",
        "time": "121m+",
        "frequency": "Extreme",
        "platforms": "7-11",
        "format": "Short-form"
    }

    # Process the user
    final_score = process_user_profile(synthetic_user_row)
    
    print(f"User Profile: {synthetic_user_row}")
    print(f"Calculated Risk Score: {final_score}%")