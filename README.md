# Kramly

**A graph-based adaptive learning-path optimizer with a genuinely agentic reasoning layer.**

---

## Table of Contents

1. [What Kramly Is](#what-kramly-is)
2. [Architecture](#architecture)
3. [The Agentic Loop](#the-agentic-loop)
4. [Human-in-the-Loop Review Governance](#human-in-the-loop-review-governance)
5. [Marketplace](#marketplace)
6. [Graph Schema](#graph-schema)
7. [Tech Stack](#tech-stack)
8. [Repository Structure](#repository-structure)
9. [Configuration & Autonomous Scheduling](#configuration--autonomous-scheduling)
10. [Running Locally](#running-locally)
11. [Testing](#testing)
12. [Known Limitations & Honest Gaps](#known-limitations--honest-gaps)
13. [What's Not Built Yet](#whats-not-built-yet)
14. [License](#license)

---

## What Kramly Is

Learners consume fragmented resources across courses, documentation, GitHub, blogs, and universities. Technical skills have complex prerequisite relationships that most learning platforms don't model systematically - roadmaps are hand-curated, go stale, and don't adapt to what a specific learner actually knows, forgets, or is running out of time for.

Kramly models the structure of knowledge as a directed acyclic graph (Neo4j) - skills as nodes, prerequisites as edges - and computes a personalized ordered learning path from a learner's current knowledge to a target skill. On top of that static-graph traversal sits an agent layer that watches learner state (skill confidence decaying over time, evidence going stale, the same skill repeatedly blocking progress) and decides what to do about it - not just "recompute the path," but chooses between several distinct actions depending on the situation.

This project went through an honest identity correction partway through development: an earlier version of this agent layer had exactly one action (recompute the path) gated by a single LLM yes/no classification, which is automation with a judgment call bolted on, not agency. The [Agentic Loop](#the-agentic-loop) section below describes what replaced it - a real action space, a grounded LLM controller, and a deterministic fallback for every step, so the system degrades gracefully rather than breaking when no LLM provider is reachable.

---

## Architecture

Four components, backed by one Neo4j Aura graph:

- **Skill Dependency Graph (Neo4j)** - `Skill` nodes and `PREREQUISITE_OF` edges. Built and extended via `graph/extraction/pipeline.py`, a human-reviewed LLM extraction pipeline (extract → CLI review → load), never auto-merged.
- **Learning Path Optimizer** (`backend/optimizer/`) - deterministic core. `planner.py` runs Kahn's algorithm for topological sort (with an optional trust-weighted variant that prefers higher-confidence edges), `decay.py` models per-skill confidence decay over time, `calibration.py` fits quality-score weights from outcome data via a hand-written OLS regression.
- **Agent Layer** (`backend/agent/`) - the reasoning core. `engine.py` orchestrates two independent proactive workflows (the original decay-triggered replan, and the newer full agentic cycle - see below), `reasoning.py` handles path critique/re-sequencing/narration, `llm_client.py` is a Groq-primary/Mistral-fallback client with no vendor SDK dependency, `recommendations.py` deterministically ranks marketplace resources per skill in a path.
- **Marketplace** (`backend/marketplace/`) - a secondary knowledge-enrichment layer: learners upload resources, the system extracts which skills they cover (LLM-grounded against the real skill list, with a heuristic keyword-matching fallback), detects near-duplicates via embeddings, scores resource quality, and tracks resource supersession over time.

![Kramly system architecture: a Neo4j Aura skill graph at the center, with the Optimizer, Agent Layer, and Marketplace reasoning over it, an Extraction Pipeline feeding proposed edges through Human-in-the-Loop Review before they ever reach the graph, and a FastAPI backend serving a React + Vite frontend](docs/sys.png)

A fifth component, `backend/review/`, is the human-in-the-loop governance layer that sits between the LLM extraction pipeline and the production graph - see [Human-in-the-Loop Review Governance](#human-in-the-loop-review-governance).

---

## The Agentic Loop

Before this existed, the agent's entire behavior was: a decay event fires, one LLM call classifies whether to replan (yes/no), and if yes, the only thing that ever happened was a path recompute. That's real LLM judgment, but over exactly one action - a navigation-system reroute with vocabulary borrowed from agent design, not the thing itself.

**The current design (`backend/agent/actions.py`, `observation.py`, `controller.py`, `executor.py`)** gives the agent a real, closed action space and a genuine observe-reason-act loop:

- **Observe** (`observation.py`) - builds a full picture of a learner: which skills have decayed, which skills keep reappearing in replans without ever being resolved (detected from decision history - a pattern a single-action system has no way to notice), which known skills have evidence old enough to be untrustworthy, and which marketplace resources are actually available for the skills that need help.
- **Reason** (`controller.py`) - deterministically generates a list of candidate actions from that observation (never lets the LLM invent an action or target a skill that isn't already justified by real data), then either lets an LLM choose among them with a stated justification, or - if the LLM proposes something outside the candidate list, or no provider is configured - falls back to a fixed priority order. This grounding pattern mirrors what `marketplace/ingestion.py` already does for concept extraction: propose freely, filter against ground truth.
- **Act** (`executor.py`) - dispatches the chosen action to a handler wired to existing capabilities (the planner for a recompute, the marketplace's resource lookup for a recommendation) and returns a structured outcome.

**The action space (`ActionType` in `actions.py`):**

| Action                   | What it does                                                                                                             |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `RECOMPUTE_PATH`         | Recalculates the learning path (the original, only-ever-existed behavior)                                                |
| `RECOMMEND_RESOURCE`     | Surfaces a specific marketplace resource for a weak or stuck skill                                                       |
| `FLAG_FOR_REINFORCEMENT` | Flags a decayed skill that has no available resource yet                                                                 |
| `REQUEST_EVIDENCE`       | Flags a known skill whose confidence is based on stale evidence                                                          |
| `ESCALATE_STUCK_LEARNER` | Flags a skill that has blocked replanning repeatedly without resolving                                                   |
| `NO_ACTION`              | Explicitly does nothing - always offered, never skipped, since a real agent must be able to conclude nothing needs doing |

Honest scope note: `RECOMMEND_RESOURCE` / `REQUEST_EVIDENCE` / `FLAG_FOR_REINFORCEMENT` / `ESCALATE_STUCK_LEARNER` produce a structured, logged recommendation, not an external side effect - there is no notification/email system in this project, and faking one would misrepresent what the code does. `RECOMPUTE_PATH` is the one action that changes stored state.

Both proactive workflows run independently on their own scheduler jobs (`AgentScheduler.run_now()` for the original decay-triggered replan, `AgentScheduler.run_agentic_cycle()` for the new loop) - the new one is additive, not a replacement, so it can never regress the old, simpler behavior even if something about the new path is wrong.

Every agentic cycle is persisted as an `AgenticDecision` node (what was observed, what was chosen and why, what executing it produced) - separate from the original `Decision` log so existing consumers of that log are unaffected. Viewable via `GET /agentic-decision-log/{learner_id}` or the "Agentic Reasoning Trace" card on the frontend's Audit Log page.

This is validated by 32 dedicated tests (`backend/tests/test_agentic_loop.py`), including a direct proof that three different learner situations (a stuck skill, an available-but-unused resource, stale evidence) produce three genuinely different chosen actions - not the same recompute every time.

---

## Human-in-the-Loop Review Governance

`backend/review/` is the gate between the LLM graph-extraction pipeline and the production Neo4j data: candidate `PREREQUISITE_OF` edges go through a strict `PENDING → APPROVED/REJECTED` state machine, and even an approved candidate is re-checked for cycles immediately before merge - trust but verify. Every state transition is logged to a structured audit trail, viewable at `GET /review/history`.

**Known limitation, stated plainly:** the candidate store (`_CANDIDATE_STORE` in `review/service.py`) is in-memory, not persisted to Neo4j - a restart clears the review queue. This is a deliberate isolation choice (nothing touches production graph data until MERGED) but it does mean pending candidates don't survive a restart; that's a real gap, not a hidden one.

---

## Marketplace

Learners can upload resources (notes, projects, flashcards, interview experiences, research summaries). Ingestion (`marketplace/ingestion.py`) hashes content for exact-duplicate detection, stores it via a pluggable storage backend, and runs LLM-grounded concept extraction - the model is given the actual list of valid skill IDs and may only match against it, with any hallucinated skill ID filtered out before linking. Near-duplicate detection (`marketplace/discovery.py`) compares embeddings via cosine similarity. Quality scoring (`marketplace/quality.py`) combines peer rating, recency, and claimed-vs-confirmed skill coverage into a single score, with weights that can be replaced by `optimizer/calibration.py`'s outcome-fitted values once enough real (or synthetic bootstrap) outcome data exists.

**Known limitation:** the embedding provider falls back to a deterministic hash-based mock vector if no Mistral API key is configured or the call fails - real similarity detection requires a working Mistral key.

---

## Graph Schema

Reflects the actual Neo4j data model, not a proposal.

**Nodes:** `Skill {id, name, domain, difficulty_level}` · `Learner {id, target_skill, deadline}` · `Resource {id, title, type, author_id, upload_date, content_hash, storage_key, status, quality_score, embedding}` · `Author {id}` · `Decision {...}` (original replan log) · `AgenticDecision {...}` (new observe-reason-act trace) · `CalibrationState {id: 'quality_weights', weight_peer_rating, weight_recency, weight_completeness, sample_count, calibrated_at, source}` · `SyntheticOutcome` (clearly-tagged calibration bootstrap data, not real usage - see [Known Limitations](#known-limitations--honest-gaps)).

**Relationships:** `(Skill)-[:PREREQUISITE_OF {crowd_confidence}]->(Skill)` · `(Learner)-[:KNOWS {confidence, last_practiced}]->(Skill)` · `(Learner)-[:HAD_DECISION]->(Decision)` · `(Learner)-[:HAD_AGENTIC_DECISION]->(AgenticDecision)` · `(Resource)-[:AUTHORED_BY]->(Author)` · `(Resource)-[:COVERS_CONCEPT {relevance_score, evidence_snippet}]->(Skill)` · `(Author)-[:RATED {score}]->(Resource)` · `(Resource)-[:SIMILAR_TO {similarity_score}]->(Resource)` · `(Resource)-[:SUPERSEDES]->(Resource)`.

`crowd_confidence` on `PREREQUISITE_OF` edges is a corroboration signal (how many distinct authors' resources cover both endpoint skills), not a discovery mechanism - it doesn't create new prerequisite relationships, only adds trust weighting to edges that already exist.

---

## Tech Stack

| Component             | What's actually used                                                                                                                                |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Graph database        | Neo4j Aura (cloud) - this project targets Aura only, no self-hosted option                                                                          |
| Backend               | Python, FastAPI, pydantic / pydantic-settings                                                                                                       |
| Agent orchestration   | Hand-rolled (no LangGraph/agent framework dependency) - dependency-injected pure functions throughout, see `agent/engine.py`, `agent/controller.py` |
| LLM calls             | Groq (primary), Mistral (fallback) via raw `httpx` REST calls - no vendor SDK                                                                       |
| Autonomous scheduling | APScheduler `BackgroundScheduler`, 4 independent jobs (see [Configuration & Autonomous Scheduling](#configuration--autonomous-scheduling))          |
| Frontend              | React + Vite, React Router, Swiss International Style design system                                                                                 |
| Testing               | pytest, 189 tests total                                                                                                                             |

**Flag:** vendor pricing/free-tier terms change often - verify Neo4j Aura's and Groq's/Mistral's current terms on their own pricing pages before relying on them for a production deployment.

---

## Repository Structure

This reflects the actual current layout.

```
kramly/
├── README.md
├── .env / env.example
│
├── graph/                          # Skill Dependency Graph layer
│   ├── db.py                       # shared Aura connection helper
│   ├── load_all_domains.py         # seed-data loader
│   ├── seed_data/                  # per-domain skill/prerequisite CSVs
│   └── extraction/
│       └── pipeline.py             # extract → review (CLI) → load, human-gated
│
├── backend/
│   ├── main.py                     # FastAPI app, CORS, lifespan, background jobs
│   ├── app/                        # config, database, graph reads, knowledge state, decay scan, decision log persistence
│   ├── optimizer/                  # planner (Kahn's algorithm), decay model, calibration (OLS)
│   ├── agent/                      # actions, observation, controller, executor, engine, reasoning, llm_client, models, recommendations
│   ├── marketplace/                # ingestion, discovery, quality, storage, embeddings, api
│   ├── review/                     # human-in-the-loop governance (models, service)
│   ├── api/                        # routes.py, review_routes.py
│   ├── models/                     # request/response Pydantic models
│   ├── scripts/                    # generate_synthetic_usage.py
│   └── tests/                      # 189 tests
│
└── frontend/
    └── src/
        ├── api/client.js
        ├── components/             # LearnerForm, PathResult, GraphVisualization, DecisionLogHistory, AgenticDecisionLog, MarketplacePanel, ...
        └── pages/                  # Home, LearningPath, Marketplace, AuditLog, SkillGraph
```

---

## Configuration & Autonomous Scheduling

Every tunable constant in the codebase - LLM temperature/max_tokens per call site, decay rate, quality-score weights, trust-weighting parameters, discovery/similarity thresholds, storage backend, CORS origins, scheduler intervals, agentic-observation thresholds (evidence staleness window, stuck-skill detection window/threshold) - lives in `backend/app/config.py`'s `Settings` (pydantic-settings `BaseSettings`, 46 fields), not scattered as module-level literals. Every field has a documented default and is overridable via environment variable or `.env`.

Four autonomous background jobs run via APScheduler once the backend starts (`main.py::_start_background_jobs`), independently of any API call:

| Job                       | Default interval | What it does                                                                        |
| ------------------------- | ---------------- | ----------------------------------------------------------------------------------- |
| `decay_scan`              | 60 min           | Original decay-triggered replan-only workflow (`AgentScheduler.run_now`)            |
| `agentic_cycle`           | 60 min           | The full observe-reason-act loop (`AgentScheduler.run_agentic_cycle`)               |
| `crowd_confidence_rescan` | 1440 min (daily) | Recomputes crowd-corroboration signal on every `PREREQUISITE_OF` edge               |
| `quality_calibration`     | 1440 min (daily) | Refits marketplace quality-score weights from outcome data, if enough samples exist |

Set `SCHEDULER_ENABLED=false` to run the API with no autonomous background jobs (used in tests).

---

## Running Locally

```bash
# Backend
cd backend
pip install -r requirements.txt   # includes apscheduler
uvicorn main:app --reload         # http://127.0.0.1:8000/docs for Swagger UI

# Seed the graph if empty
cd graph
python load_all_domains.py

# Frontend
cd frontend
npm install
npm run dev
```

Requires a `.env` at the project root with `NEO4J_URI`, `NEO4J_USERNAME`/`NEO4J_USER`, `NEO4J_PASSWORD`, and optionally `GROQ_API_KEY`/`MISTRAL_API_KEY` (the system runs on deterministic fallbacks everywhere an LLM call would otherwise happen, but the "agentic" behavior is much thinner without a real provider configured). See `env.example` for every optional setting.

---

## Testing

189 tests (`cd backend && python -m pytest`). As of the last full run: **186 passed, 3 failed** - the 3 failures are `tests/test_integration.py` tests that require a live Neo4j Aura connection and fail in any environment without one configured; they are not flaky unit tests. Run `pyflakes` alongside `pytest` if you touch LLM-facing code - it catches undefined-name bugs (e.g. a truncated variable reference) that `ast.parse`/syntax checks alone miss.

---

## Known Limitations & Honest Gaps

Stated directly rather than left for someone else to discover:

- **Calibration runs on synthetic data only.** `optimizer/calibration.py`'s outcome-fitted quality weights are currently calibrated exclusively against `:SyntheticOutcome` bootstrap nodes (`scripts/generate_synthetic_usage.py`). The regression math is independently verified correct, but a correct fit on synthetic data is not evidence the resulting weights are better than the static defaults in the real world. Delete `:SyntheticOutcome` nodes once real usage data exists.
- **No authentication anywhere.** Every API endpoint is unauthenticated. The marketplace's rating endpoint currently receives a hardcoded `"student_user"` author ID from the frontend rather than a real identity.
- **Cloud storage backend is unimplemented.** `storage_backend` supports `"local"` only; `"cloud"` is a documented but unbuilt option.
- **The review governance queue is in-memory**, not Neo4j-persisted - see [Human-in-the-Loop Review Governance](#human-in-the-loop-review-governance).
- **Decay rate, quality-score weights (pre-calibration), and trust-weighting formulas are original heuristics**, not citations of published research (spaced-repetition literature like Anki's SM-2 or Duolingo's half-life regression are real, relevant reference points if you want to make this rigorous, but nothing in this codebase currently implements or validates against them).
- **The `RECOMMEND_RESOURCE`/`REQUEST_EVIDENCE`/`FLAG_FOR_REINFORCEMENT`/`ESCALATE_STUCK_LEARNER` actions have no external side effect** - no notification or messaging system exists, so these produce a logged recommendation a human has to go look at, not a proactive nudge to the learner.
- **`graph/extraction/pipeline.py` is a manual, human-run CLI tool**, not something that runs automatically - extending the graph with new content requires someone to run `extract` → `review` → `load` themselves.

---

## What's Not Built Yet

- **CI/CD.** No GitHub Actions workflow exists yet (no `.github/workflows/`). Tests must be run manually.
- **Deployment.** The project runs locally only; no AWS EC2 (or other hosting) deployment has been done. If/when this happens, Neo4j Aura's free tier (separate from wherever the API is hosted) is the intended graph database placement - verify current AWS free-tier terms directly on AWS's billing dashboard before relying on them, as these change over time.
- **Real usage data.** Nothing in this project has been calibrated, validated, or load-tested against real learners yet - every "adaptive" or "calibrated" claim in this README is honest about running on synthetic or hand-constructed data until that changes.

---

## License

MIT - see [LICENSE](LICENSE). Chosen because this is a solo, personal project with no commercial product to protect: MIT is the simplest permissive option, imposes no restriction on how others use or build on the code, and is the license reviewers/employers recognize on sight without needing to read it.
