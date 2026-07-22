"""
config.py
---------
Centralised configuration for the Kramly backend.

Design decisions
~~~~~~~~~~~~~~~~
1. **pydantic-settings** (`BaseSettings`) is used instead of raw
   ``os.getenv()`` calls.  This gives us:
   - Automatic type coercion and validation at startup.
   - A single, importable ``settings`` object — no scattered getenv().
   - Built-in ``.env`` file loading without manually calling ``load_dotenv()``.
   - Frozen model — settings are immutable after creation, preventing
     accidental mutation at runtime.

2. The ``.env`` file is resolved relative to the *project root*
   (two levels above ``backend/app/``), so it's shared by the backend
   and the graph-loading scripts under ``graph/``.

3. ``NEO4J_USERNAME`` is the canonical name. ``validation_alias`` also
   accepts ``NEO4J_USER``, since that's the field name Aura's own
   downloaded credentials file uses.

4. **Every tunable constant lives here, not scattered as module-level
   literals.** Decay rates, quality-score weights, trust-weighting
   parameters, LLM call parameters (temperature/max_tokens/timeout),
   CORS origins, storage backend selection, and scheduler intervals were
   previously hardcoded directly in optimizer/decay.py, app/decay_scanner.py,
   marketplace/quality.py, agent/reasoning.py, agent/llm_client.py, and
   backend/main.py. They're all fields here now, each with a default that
   matches the previous hardcoded value, so behavior is unchanged out of
   the box but every one of these numbers is now an env var away from being
   tuned without touching code.

   Honesty note carried over from the original constants: the decay rate,
   quality-score weights, and trust-weighting parameters were never
   validated against real usage — they're reasonable starting points, not
   citations of research. Making them configurable doesn't make them
   correct; it makes them adjustable once real data says they're wrong.
   See ``optimizer/calibration.py`` for the mechanism intended to
   eventually replace these static defaults with outcome-fitted values.

5. **Test files intentionally do NOT read from this Settings object.**
   Unit tests construct their own fixed inputs (e.g. pass an explicit
   ``decay_rate=0.03`` to a function under test) so they stay deterministic
   regardless of what's in a developer's ``.env``. Only production code
   paths route through ``settings``.
"""

import os
from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

# Resolve the project root: backend/app/config.py  ->  ../../.env
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings populated from environment variables / ``.env``."""

    # --- Neo4j Aura connection ---
    neo4j_uri: str = Field(
        ...,
        description=(
            "Connection URI for the Neo4j Aura (cloud) instance, e.g. "
            "neo4j+s://<db-id>.databases.neo4j.io. Get one at "
            "https://console.neo4j.io. Local Neo4j Desktop/Community is not "
            "used or supported by this project."
        ),
    )
    neo4j_username: str = Field(
        default="neo4j",
        validation_alias=AliasChoices("NEO4J_USERNAME", "NEO4J_USER"),
        description="Neo4j authentication username.",
    )
    neo4j_password: str = Field(
        ...,
        description="Neo4j authentication password.",
    )

    # --- Agentic LLM providers (Groq primary, Mistral fallback) ---
    groq_api_key: Optional[str] = Field(
        default=None,
        description="API key for Groq (primary LLM provider for agent reasoning).",
    )
    groq_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="Groq model ID used for agent decision-making and narration.",
    )
    mistral_api_key: Optional[str] = Field(
        default=None,
        description="API key for Mistral (fallback LLM provider if Groq fails/unset).",
    )
    mistral_model: str = Field(
        default="mistral-small-latest",
        description="Mistral model ID used as fallback for agent reasoning.",
    )
    mistral_embedding_model: str = Field(
        default="mistral-embed",
        description="Mistral model ID used for marketplace resource embeddings.",
    )
    llm_request_timeout_seconds: float = Field(
        default=20.0,
        description="Per-request timeout (seconds) applied to both Groq and Mistral calls.",
    )

    # --- LLM call parameters, per call site (temperature/max_tokens) ---
    llm_trigger_judgment_temperature: float = Field(default=0.1, description="Temperature for agent/engine.py's replan-trigger judgment call.")
    llm_trigger_judgment_max_tokens: int = Field(default=200, description="Max tokens for the replan-trigger judgment call.")
    llm_path_reorder_temperature: float = Field(default=0.3, description="Temperature for agent/reasoning.py's LLM path re-sequencing call.")
    llm_path_reorder_max_tokens: int = Field(default=400, description="Max tokens for the LLM path re-sequencing call.")
    llm_critique_temperature: float = Field(default=0.2, description="Temperature for agent/reasoning.py's qualitative path critique call.")
    llm_critique_max_tokens: int = Field(default=500, description="Max tokens for the qualitative path critique call.")
    llm_narration_temperature: float = Field(default=0.4, description="Temperature for agent/reasoning.py's decision narration call.")
    llm_narration_max_tokens: int = Field(default=250, description="Max tokens for the decision narration call.")
    llm_extraction_temperature: float = Field(default=0.1, description="Temperature for marketplace/ingestion.py's concept-extraction call.")
    llm_extraction_max_tokens: int = Field(default=800, description="Max tokens for marketplace/ingestion.py's concept-extraction call.")
    llm_graph_extraction_max_tokens: int = Field(default=1200, description="Max tokens for graph/extraction/pipeline.py's candidate-edge extraction call.")
    llm_json_retry_temperature: float = Field(default=0.0, description="Temperature used for the single stricter-JSON retry in complete_json().")

    # --- Adaptive decay model (optimizer/decay.py, app/decay_scanner.py) ---
    decay_rate_per_day: float = Field(
        default=0.03,
        description=(
            "Exponential decay rate applied to skill confidence per day "
            "since last practiced. Arbitrary starting value, not derived "
            "from a validated forgetting-curve model — see optimizer/decay.py."
        ),
    )
    decay_threshold: float = Field(
        default=0.5,
        description="Decayed-confidence threshold below which a skill is flagged for proactive replanning.",
    )

    # --- Marketplace quality scoring (marketplace/quality.py) ---
    quality_weight_peer_rating: float = Field(default=0.5, description="Weight of average peer rating in the resource quality score.")
    quality_weight_recency: float = Field(default=0.2, description="Weight of recency in the resource quality score.")
    quality_weight_completeness: float = Field(default=0.3, description="Weight of claimed-vs-confirmed skill coverage in the resource quality score.")
    quality_recency_decay_rate_per_day: float = Field(
        default=0.01,
        description="Exponential decay rate for the recency component of the quality score (slower than learner-confidence decay).",
    )

    # --- Marketplace discovery/similarity (marketplace/discovery.py) ---
    marketplace_similarity_threshold: float = Field(
        default=0.5,
        description="Minimum cosine-similarity score for two resources to be linked as SIMILAR_TO.",
    )
    marketplace_duplicate_threshold: float = Field(
        default=0.95,
        description="Cosine-similarity score at/above which two resources are flagged as near-duplicates.",
    )
    ranking_base_score: float = Field(default=100.0, description="Starting score for the first (newest) resource in BaseDateRankingStrategy.")
    ranking_score_decrement: float = Field(default=5.0, description="Score reduction per rank position in BaseDateRankingStrategy.")
    ranking_score_floor: float = Field(default=1.0, description="Minimum score BaseDateRankingStrategy will ever assign.")

    # --- Trust-weighted path ordering (agent/reasoning.py) ---
    trust_weighting_epsilon: float = Field(default=0.01, description="Epsilon term in the inverse-confidence trust-weighting formula (avoids divide-by-zero).")
    trust_weighting_min_weight: float = Field(default=0.01, description="Floor value below which a trust-weighted edge cost is never allowed to fall.")
    trust_weighting_discount_factor: float = Field(default=0.5, description="Discount factor in the linear trust-weighting formula.")

    # --- Marketplace storage backend ---
    storage_backend: str = Field(
        default="local",
        description="Which StorageBackend implementation to use: 'local' or 'cloud' (cloud is not yet implemented).",
    )
    local_storage_dir: str = Field(
        default="./marketplace_files",
        description="Directory LocalFileStorage writes uploaded resource content to.",
    )

    # --- API / CORS ---
    cors_allow_origins: str = Field(
        default="*",
        description=(
            "Comma-separated list of allowed CORS origins, or '*' for all. "
            "'*' is fine for local development; set this to your real "
            "frontend origin(s) before exposing the API beyond localhost."
        ),
    )

    # --- Autonomous scheduler ---
    decay_scan_interval_minutes: int = Field(
        default=60,
        description="How often the background scheduler runs the proactive decay scan (AgentScheduler.run_now()).",
    )
    calibration_interval_minutes: int = Field(
        default=1440,
        description="How often the background scheduler recomputes quality/trust weights from outcome data (default: daily).",
    )
    scheduler_enabled: bool = Field(
        default=True,
        description="Master switch for the background scheduler. Set to false to run the API with no autonomous background jobs (e.g. in tests).",
    )
    calibration_min_samples: int = Field(
        default=10,
        description=(
            "Minimum number of outcome records optimizer/calibration.py needs "
            "before it will compute and persist calibrated quality weights. "
            "Below this, calibrate_quality_weights() returns None and the "
            "static Settings.quality_weight_* defaults keep being used."
        ),
    )

    # --- Agentic observation (agent/observation.py) ---
    evidence_staleness_days: int = Field(
        default=60,
        description=(
            "A known skill whose last_practiced evidence is older than this "
            "many days is flagged as stale during agentic observation, "
            "separate from decay-confidence math (optimizer/decay.py) - this "
            "is about how old the evidence itself is, not the computed "
            "confidence value."
        ),
    )
    stuck_skill_repeat_threshold: int = Field(
        default=2,
        description=(
            "A skill that appears in added_skills across at least this many "
            "of the learner's last stuck_skill_lookback_window decisions "
            "without ever being learned is flagged as a stuck skill by "
            "agent/observation.py."
        ),
    )
    stuck_skill_lookback_window: int = Field(
        default=3,
        description="Number of most recent decision-log entries agent/observation.py inspects when detecting stuck skills.",
    )
    marketplace_candidates_per_skill: int = Field(
        default=3,
        description="Max number of marketplace resources agent/observation.py attaches per weak/stuck skill when building an observation.",
    )

    @property
    def cors_allow_origins_list(self) -> list[str]:
        """Parsed form of cors_allow_origins for passing to CORSMiddleware."""
        if self.cors_allow_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    model_config = {
        "env_file": str(_PROJECT_ROOT / ".env"),
        "case_sensitive": False,
        "frozen": True,
        "extra": "ignore",
    }


settings = Settings()
