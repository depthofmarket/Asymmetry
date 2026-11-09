"""
Strategies package initialization.
Exports Candidate Strategy S4 (Asian Evening Reversion).
"""

from strategies.asian_evening_reversion_s4 import (
    AsianEveningReversionParams,
    AsianEveningReversionS4,
    calculate_asian_session_features,
    generate_signals,
    simulate_intrabar_execution,
)
from strategies.crude_rth_expansion_s5 import (
    CrudeRthExpansionParams,
    CrudeRthExpansionS5,
    calculate_crude_rth_features,
)

__all__ = [
    "AsianEveningReversionParams",
    "AsianEveningReversionS4",
    "calculate_asian_session_features",
    "generate_signals",
    "simulate_intrabar_execution",
    "CrudeRthExpansionParams",
    "CrudeRthExpansionS5",
    "calculate_crude_rth_features",
]

