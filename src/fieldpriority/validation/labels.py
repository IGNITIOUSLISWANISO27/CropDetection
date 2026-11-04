"""Kobo choice codes -> labels used by the Validation Register (from the XLSForm 'choices' sheet)."""
RECORD_TYPE = {"test": "TEST", "real_visit": "REAL FIELD VISIT"}
RISK = {"low": "Low", "watch": "Watch", "moderate": "Moderate", "high": "High",
        "insufficient_data": "Insufficient data", "not_available": "Not available"}
STAGE = {"emergence": "Emergence", "early_vegetative": "Early vegetative", "vegetative": "Vegetative growth",
         "tasselling_silking": "Tasselling/silking", "grain_filling": "Grain filling",
         "maturity_harvest": "Maturity/harvest", "unknown": "Unknown"}
VERDICT = {"confirmed": "Confirmed", "rejected": "Rejected", "uncertain": "Uncertain"}
# register column 'Alternative Cause' (drought itself means there is no alternative cause)
ALT_CAUSE = {"drought_stress": "None", "pest_disease": "Pest/disease", "nutrient_issue": "Nutrient issue",
             "late_planting": "Late planting", "waterlogging": "Waterlogging/flooding",
             "mixed": "Mixed causes", "unknown": "Unknown"}
NEXT_STEP = {"monitor": "Continue monitoring", "repeat_verify": "Repeat field verification",
             "assess_water": "Assess water availability", "extension_support": "Provide extension support",
             "technical_assessment": "Refer for technical assessment", "other": "Other"}
# Kobo 'system_risk' code -> rules risk levels it can stand for (Kobo choices predate the rules;
# agree new choices with Person 3 before changing the form)
# Form choices -> system risk levels they agree with. 'watch' and 'insufficient_data' are for the form update
# proposed in Nov 2026; until then a Watch alert was recorded as 'low' (older records still accepted).
RISK_TO_LEVELS = {"high": {"High"}, "moderate": {"Moderate"}, "watch": {"Watch"}, "low": {"Low", "Watch"},
                  "insufficient_data": {"Insufficient data"},
                  "not_available": {"Not attributed", "Insufficient data", "Not assessed"}}
EARLY_STAGES = {"emergence", "early_vegetative", "vegetative"}
DRY_SOIL = {"dry", "very_dry", "cracked"}
