"""Turn raw indicators into 0-1 scores. 1 = highest priority for verification."""
import numpy as np
import pandas as pd


def cohort_minmax(series, higher_is_stress):
    """Min-max across the pilot fields (replicates v1). Relative ranking, not absolute stress."""
    s = pd.to_numeric(series, errors="coerce")
    lo, hi = s.min(), s.max()
    if not np.isfinite(lo) or hi - lo == 0:
        return pd.Series(0.0, index=s.index).where(s.notna())
    out = (s - lo) / (hi - lo) if higher_is_stress else (hi - s) / (hi - lo)
    return out.clip(0, 1)


def fixed_reference(series, neutral, severe):
    """Linear 0-1 between a neutral value (score 0) and a severe value (score 1)."""
    s = pd.to_numeric(series, errors="coerce")
    return ((s - neutral) / (severe - neutral)).clip(0, 1)
