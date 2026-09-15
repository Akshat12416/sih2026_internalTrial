"""
core/config.py
==============
Central feature flags for the layered fleet architecture (Part C / Part D of
Fleet Architecture Guide).

Flags default to False to preserve baseline behavior, and can be toggled
programmatically or via environment variables for benchmarking.
"""
import os

USE_DIRECTED_GRAPH: bool = os.getenv("USE_DIRECTED_GRAPH", "0").lower() in ("1", "true", "yes")
USE_PIBT: bool = os.getenv("USE_PIBT", "0").lower() in ("1", "true", "yes")
USE_WAITFOR_GRAPH: bool = os.getenv("USE_WAITFOR_GRAPH", "0").lower() in ("1", "true", "yes")
USE_CONGESTION_COST: bool = os.getenv("USE_CONGESTION_COST", "0").lower() in ("1", "true", "yes")
USE_DSTAR_LITE: bool = os.getenv("USE_DSTAR_LITE", "0").lower() in ("1", "true", "yes")
USE_BATCHING: bool = os.getenv("USE_BATCHING", "0").lower() in ("1", "true", "yes")
