# Kramly

**An agentic AI system that models the structure of knowledge itself and continuously re-plans a learner's optimal path through it.**

> **Note on the name:** "Kramly" is derived from the Sanskrit/Hindi word _Krama_ (क्रम — sequence, order). I am not a certain, fluent authority on Sanskrit/Hindi etymology — before using this name publicly, verify the root word's meaning and connotation with a native speaker or reliable dictionary.

---

## Table of Contents

1. [Background & Problem Statement](#background--problem-statement)
2. [Why This Is Agentic (Not Just RAG)](#why-this-is-agentic-not-just-rag)
3. [Architecture](#architecture)
4. [Tech Stack](#tech-stack)
5. [Graph Schema](#graph-schema)
6. [Repository Structure](#repository-structure)
7. [Detailed Phase-Wise Plan](#detailed-phase-wise-plan)
8. [AWS EC2 Deployment Plan](#aws-ec2-deployment-plan)
9. [Production-Grade Design Decisions](#production-grade-design-decisions)
10. [Team & Work Split](#team--work-split)
11. [Open Questions](#open-questions)
12. [Roadmap Status](#roadmap-status)
13. [Novelty Verification](#novelty-verification)
14. [Notes, Assumptions & Things to Verify](#notes-assumptions--things-to-verify)
15. [License](#license)

---

## Background & Problem Statement

The rapid evolution of technology has created thousands of interconnected skills across software engineering, AI, cloud computing, cybersecurity, and data science. Learners consume fragmented resources from courses, documentation, GitHub, blogs, and universities. Technical skills possess complex prerequisite relationships that are rarely modeled systematically.

Existing learning platforms rely on manually curated roadmaps that quickly become outdated. They do not automatically discover prerequisite relationships or personalize learning based on a learner's actual knowledge. Traditional educational platforms also provide fixed learning sequences regardless of prior knowledge, performance, career goals, or deadlines — human learning is dynamic, but current systems rarely adapt roadmaps as learner behavior changes.

**Existing problems this project addresses:**

- Static roadmaps become outdated.
- Hidden prerequisite gaps remain undetected.
- Dependencies are manually maintained.
- Learners study concepts in the wrong order.
- Recommendation systems optimize engagement rather than learning efficiency.
- Weak concepts remain hidden from the learner.
- Recommendations ignore deadlines.
- Progress tracking rarely changes future learning paths.
- No continuous optimization of the learning sequence.

**Research gap:** Current systems recommend learning resources ("what to study next"). Kramly instead models the structure of knowledge itself — answering "what must a learner know before studying this concept?" — and determines the optimal _sequence_ of learning based on a continuously evolving learner profile, behaving like a navigation system that recalculates whenever new evidence becomes available.

---

## Why This Is Agentic (Not Just RAG)

Kramly is not a retrieval-augmented chatbot answering questions about skills. It is a system that:

- **Maintains state** — a learner's evolving knowledge profile.
- **Makes autonomous decisions** — recomputing a learning path in response to new evidence (a quiz result, a missed deadline, a decayed skill) without being explicitly asked each time.
- **Logs its own reasoning** — every re-planning decision records what changed and why, a core agentic-transparency property, not a retrieval property.
- **(Stretch goal) Governs its own outputs** — in Phase 3, an LLM proposes new graph edges, but a human-in-the-loop gate is required before anything is merged into production data. This models responsible agent-output governance rather than autonomous self-modification.
- **Does not use LLM fine-tuning** — the project is deliberately built on orchestration, tool-use, graph reasoning, and planning logic rather than training/fine-tuning a model.

---

## Architecture

Two layers, built to work together as a cohesive platform rather than isolated applications:

- **Layer 1 — Skill Dependency Graph (the knowledge layer):** a graph database storing skills as nodes and prerequisite relationships as directed edges. Continuously discovers, updates, and reasons over prerequisite relationships extracted from educational resources, enabling accurate identification of knowledge gaps and learner readiness.
- **Layer 2 — Learning Path Optimizer (the agent layer):** an agent that reads a learner's current knowledge state, traverses the graph, and computes/recomputes an optimal sequence of skills to learn, re-running whenever new evidence arrives (quiz result, forgotten concept, changed deadline) — an adaptive roadmap engine that behaves like a navigation system.

```
┌─────────────────────────┐        ┌──────────────────────────────┐
│  Skill Dependency Graph  │◄──────►│  Learning Path Optimizer      │
│  (Neo4j)                 │        │  (FastAPI + agent logic)      │
│                           │        │                                │
│  Skill nodes              │        │  - Reads learner state         │
│  PREREQUISITE_OF edges    │        │  - Traverses graph              │
└─────────────────────────┘        │  - Computes ordered path        │
                                     │  - Triggers on new evidence    │
                                     │  - Logs every decision          │
                                     └──────────────────────────────┘
```

_(A proper visual architecture diagram is a Phase 5 deliverable — this is a simplified text version for the README.)_

A third component — a **Student Knowledge Marketplace** (transforming uploaded educational content into a semantic knowledge graph, extracting concepts, linking resources, detecting duplicates, evaluating quality) — was considered as a way to continuously enrich the graph with community knowledge, but is **out of scope for the current build** in favor of shipping a focused two-layer MVP first.

---

## Tech Stack

**Flag:** free-tier limits and exact current offerings change often. Verify all of the below on the vendor's current pricing page before committing — I'm not fully certain these are all still accurate as of your build date.

| Component                | Suggested Free Option                                                               | Note                                                                                                                  |
| ------------------------ | ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Graph database           | Neo4j Aura Free tier, or self-hosted Neo4j Community Edition                        | Verify current Aura free-tier node/relationship limits                                                                |
| Backend/API              | Python (FastAPI) or Node.js                                                         | Your choice based on comfort                                                                                          |
| Agent orchestration      | LangGraph, or hand-rolled state machine                                             | I am not fully certain of LangGraph's current exact API — verify against official docs before writing code against it |
| LLM calls (Phase 3 only) | Free-tier from a provider (e.g., Groq, Google Gemini free tier) or local via Ollama | I do not have verified current free-tier limits for any of these — check each provider's pricing page directly        |
| Hosting                  | AWS EC2 (see [AWS EC2 Deployment Plan](#aws-ec2-deployment-plan))                   | Free tier exists but has strict limits and a time window — verify current terms before relying on it                  |
| CI/CD                    | GitHub Actions                                                                      | Free tier for public repos, generous free minutes for private repos as of my knowledge — verify current limits        |
| Frontend (optional)      | React + a graph visualization library (e.g., react-force-graph or Cytoscape.js)     | Verify current library names/APIs — I am not fully certain these libraries' APIs haven't changed                      |

---

## Graph Schema

This is a proposed schema, not a verified industry standard — adjust based on your actual data.

**Node: Skill**

- `id`
- `name`
- `domain` (e.g., "ML", "Web Dev")
- `difficulty_level` (optional)

**Edge: PREREQUISITE_OF**

- `from_skill_id`
- `to_skill_id`
- `strength` (optional — how strict the prerequisite is; not all prerequisites are equally mandatory)
- `source` (`manual` / `extracted` — important for Phase 3 traceability)

**Node: Learner** (added in Phase 1 for state tracking)

- `id`
- `known_skills` (list, with confidence/decay metadata)
- `target_skill`
- `deadline` (optional)

---

## Repository Structure

**This is a proposed structure, not yet an existing/verified one** — adjust it once you've made concrete tooling decisions (e.g., Python vs. Node, monorepo vs. split repos). I'm presenting this as a reasonable starting layout, not a fact about your actual codebase.

```
kramly/
├── README.md
├── .gitignore
├── .env.example
├── requirements.txt              # or package.json if using Node
│
├── graph/                        # Layer 1 — Skill Dependency Graph
│   ├── schema/
│   │   └── schema_definitions.md
│   ├── seed_data/
│   │   ├── skills.csv
│   │   └── prerequisites.csv
│   ├── load_graph.py             # script to populate Neo4j from seed data
│   └── extraction/                # Phase 3 stretch goal
│       ├── extract_candidates.py
│       └── review_interface/
│
├── optimizer/                    # Layer 2 — Learning Path Optimizer (agent)
│   ├── traversal.py               # core pure traversal/optimizer function
│   ├── decay_model.py             # Phase 2 forgetting model
│   ├── replanning_triggers.py     # Phase 2 event handling
│   └── decision_log.py            # agentic reasoning transparency log
│
├── api/                          # FastAPI (or equivalent) layer
│   ├── main.py
│   ├── routes/
│   │   ├── path.py
│   │   └── learner.py
│   └── models/                    # request/response schemas
│
├── tests/
│   ├── test_traversal.py
│   ├── test_replanning.py
│   └── test_api_integration.py
│
├── infra/                        # Phase 4 — AWS EC2 deployment
│   ├── deploy.sh
│   ├── systemd/
│   │   └── kramly.service
│   ├── nginx/
│   │   └── kramly.conf
│   └── github-actions/
│       └── deploy.yml
│
├── frontend/                     # optional
│   └── (React app, if built)
│
└── docs/
    ├── architecture-diagram.png   # Phase 5 deliverable
    ├── novelty-verification.md
    └── demo-notes.md
```

---

## Detailed Phase-Wise Plan

**How to read this section:** phases are milestone-based, not fixed to specific week counts. Each phase lists tasks, deliverables, and a "verify before building" note where current tool syntax/limits are not something I can guarantee. Treat every such flag as a real instruction to check current docs, not a formality.

### Phase 0 — Setup & Foundations

**Goal:** Environment ready, no ambiguity left before feature code is written.

1. Create/confirm your AWS account and check the Billing/Free Tier dashboard directly, so you know your actual free-tier status before relying on it.
2. Decide your backend language (Python/FastAPI recommended given the AI/data ecosystem, but Node.js is equally valid).
3. Set up local dev environment: virtual environment (or Node equivalent), Git repo, `.gitignore`, basic project structure.
4. Install Neo4j locally (Community Edition, free) for development.
5. Set up a GitHub repo with branch protection basics and a README skeleton.
6. **Verify before building:** current FastAPI installation/quickstart steps and current Neo4j Desktop/Community download + local connection steps from their respective official docs.

**Deliverable:** A working local environment where you can start a FastAPI server and connect to a local Neo4j instance and run a basic query.

### Phase 1 — MVP: Seeded Graph + Basic Optimizer Agent

**Goal:** A working end-to-end demo: static graph in, learner state in, ordered learning path out.

**1.1 Data modeling**

- Finalize the graph schema.
- Pick ONE domain you can personally validate for correctness (e.g., "Python → Data Structures → Algorithms → ML Basics → Deep Learning" or a web-dev stack).
- Hand-curate 30–80 skill nodes and their prerequisite edges as structured data (CSV/JSON) before touching the database.

**1.2 Graph database population**

- Write a script to load the CSV/JSON into Neo4j (Cypher `CREATE`/`MERGE` statements, or a Python driver script).
- **Verify before building:** the current Neo4j Python driver's exact import and connection syntax from Neo4j's official driver docs.
- Manually inspect the graph in Neo4j's browser UI to confirm structure before writing application code against it.

**1.3 Core traversal/optimizer logic**

- Implement the core algorithm: given a learner's known-skills set and a target skill, compute an ordered path (topological sort / shortest-path over a DAG — confirm your graph is actually acyclic).
- Write this as a pure, testable function first, separate from any API/agent wrapper.
- **Verify before building:** whether to implement traversal in Python (e.g., `networkx` — confirm current API) versus a native Cypher path-finding query (confirm current syntax from Neo4j's docs).

**1.4 API layer**

- Build FastAPI (or equivalent) endpoints: submit known skills + target skill → receive ordered path.
- Add input validation and error handling (invalid skill IDs, unreachable targets, etc.).

**1.5 Minimal agent framing**

- Wrap the optimizer logic as an "agent" with an explicit decision log — every computed path logs its inputs and reasoning. This is the seed of the "agentic reasoning transparency" story for interviews.

**1.6 Testing**

- Unit tests for traversal logic edge cases (no path exists, learner already knows everything, cyclic data caught and rejected).
- Basic integration test hitting the API end-to-end.

**Deliverable:** A working local API that takes learner state + target skill and returns a valid ordered learning path, with logs and tests.

### Phase 2 — Adaptive Re-Planning

**Goal:** Move from static to dynamic — the system reacts to new evidence.

**2.1 Knowledge state tracking**

- Record "evidence" of learning: quiz results, self-report checkboxes, or both.
- Store per-skill confidence/mastery state on the Learner node or a related table.

**2.2 Decay/forgetting model**

- Implement a decay function: skills unused for N days reduce in confidence.
- **Flag:** there is no single verified "standard" formula to hand you off the shelf. Spaced-repetition systems like Anki's SM-2 algorithm are a real, documented reference point, but confirm the actual formula from Anki's own documentation rather than from memory — I am not fully certain I would reproduce it correctly.
- A basic linear or exponential decay you define yourself is a legitimate MVP choice.

**2.3 Re-planning triggers**

- Define concrete trigger events: quiz completed, decay threshold crossed, deadline changed, new target skill set.
- Implement an event handler that calls the Phase 1 optimizer again on trigger, and diffs the new path against the old one.

**2.4 Decision logging (expanded)**

- Log _what changed_ between the old path and new path, and _why_ (which trigger fired) — a strong demoable feature.

**2.5 Testing**

- Test that re-planning is idempotent (running it twice on unchanged state doesn't produce a different or duplicated result).

**Deliverable:** A system that behaves like a "navigation system" for learning — recalculating when new evidence arrives, with a visible reasoning trail.

### Phase 3 — Semi-Automated Graph Extraction (Stretch Goal)

**Goal:** Reduce manual graph-building effort using LLM-assisted extraction, with human review as a hard gate.

**3.1 Source selection**

- Choose ONE text source type (e.g., open syllabi, public curricula, documentation). Confirm you're legally permitted to use/scrape it — check the source's terms of service yourself.

**3.2 Extraction pipeline**

- Use an LLM (local via Ollama, or a free-tier hosted API) to propose candidate prerequisite relationships from source text.
- **Verify before building:** current setup/API syntax for whichever LLM access method you choose, and current free-tier limits, directly from the provider.
- Output candidate edges in a reviewable format (proposed edge, source text snippet, confidence).

**3.3 Human-in-the-loop review**

- Build a simple review interface (a basic web form or CLI tool is fine) where candidate edges are approved/rejected before merging into the production graph.
- Never auto-merge LLM output directly — this is a deliberate design choice demonstrating agent-output governance.

**3.4 Merge and re-validate**

- After approval, merge new edges into the graph and re-run cycle-detection (the Phase 1.3 acyclic-structure assumption must hold).

**Deliverable:** A working (even if narrow/small-scale) semi-automated pipeline that expands the graph with human oversight.

---

## AWS EC2 Deployment Plan

**Goal (Phase 4):** Move from "working on my laptop" to a deployed, observable, cost-controlled system.

**Uncertainty flag upfront:** AWS's free tier terms (which instance types qualify, the duration, and the monthly hour caps) have changed over time and are not something I can guarantee are current. Verify directly on AWS's official free tier page before launching anything.

**4.1 Pre-deployment checklist**

- Confirm AWS free-tier status directly in your Billing dashboard.
- Decide: Neo4j on the same EC2 instance vs. Neo4j Aura free tier separately.

**4.2 EC2 setup**

- Launch instance (verify current free-tier-eligible instance type and AMI in the AWS console at launch time — do not assume `t2.micro`/`t3.micro` is still accurate without checking).
- Configure Security Group to allow inbound traffic only on needed ports (22 for SSH, 80/443 for web traffic, your API port).
- Set up SSH key access; consider disabling password auth per current AWS/Ubuntu hardening guidance (verify from official docs).

**4.3 Graph database placement**

- **Option A:** Run Neo4j Community Edition directly on the same EC2 instance — simpler, but the instance does double duty as app server + database.
- **Option B:** Run Neo4j Aura's free tier separately, with the EC2-hosted API connecting over the network — cleaner separation of concerns, closer to real production architecture. This is a judgment call, not a fact — decide based on what you want to demonstrate.

**4.4 App deployment on the instance**

- `systemd` service files (to keep the API running after reboot/disconnect) or Docker. Verify current best-practice guidance in AWS's own EC2 documentation rather than assuming.
- Set environment variables/secrets securely (never commit them to Git) — a `.env` file excluded via `.gitignore`, or AWS Systems Manager Parameter Store for a more advanced setup (verify current setup steps from AWS's own docs).

**4.5 CI/CD to EC2**

- GitHub Actions can SSH into the instance and redeploy on push. Verify the current, actively maintained SSH-deploy action on the GitHub Marketplace before wiring this up — I don't want to hand you a specific action name I can't confirm is current and maintained.

**4.6 Observability & cost control**

- Extend decision logs with system-level logs (errors, response times).
- Set up AWS Budgets with a low-dollar alert threshold so an instance left running doesn't silently accrue charges once free-tier hours or the window are exhausted.
- Optional: a simple `/health` endpoint for uptime checks.

**4.7 Domain/HTTPS (optional, for polish)**

- Nginx as reverse proxy, with a free TLS certificate (Let's Encrypt / Certbot is the standard free option, though verify current setup steps from Certbot's own docs).

**Deliverable:** A live, publicly accessible (or demo-able) deployment on AWS EC2, with basic cost controls and observability in place.

---

## Production-Grade Design Decisions

Based on general software engineering practice (not a cited source, just standard practice), this project is explicitly designed to go beyond a basic demo:

1. **Structured logging** of every agent decision — what the optimizer changed and why.
2. **Idempotency** — re-running the optimizer on the same state shouldn't produce inconsistent results or duplicate graph writes.
3. **Human-in-the-loop gating** for any graph edits from Phase 3's LLM extraction — never auto-merge.
4. **Automated tests** for the graph traversal logic — pure algorithmic code, very testable, a real strength point for a portfolio.
5. **CI/CD deployment**, not manual deploys.
6. **Observability** — even a simple dashboard showing graph size, number of re-plans triggered, etc.
7. **Cost control** — AWS Budgets alerting on the deployment infrastructure.

---

## Team & Work Split

Two-person team, phase-based split restructured into **parallel, thematic tracks** rather than strict sequential phase ownership — a strict "one person does Phases 0-2 while the other waits" approach would leave one person idle for a long stretch, since Phase 3/4 work depends on Phase 1/2 output existing. Both people work within every phase, on different tracks, in parallel.

### Phase 0 (Both, in parallel)

- **Person A:** AWS account setup, Billing/Free Tier dashboard check, GitHub repo creation, branch protection, README skeleton.
- **Person B:** Local dev environment, Neo4j Community Edition local install, verify local connection works.
- **Together:** Agree on the graph schema before either writes code against it.

### Phase 1

- **Person A — Data/Graph track:** domain selection, hand-curating skill nodes/edges, load script, manual graph validation.
- **Person B — Logic/API track:** core traversal/optimizer function, FastAPI endpoints, unit tests.
- **Together, at the end:** integration test — A's data through B's logic, end to end.
- _Dependency note:_ B can build/test against a small dummy graph while A finishes the full dataset — B is not blocked.

### Phase 2

- **Person A — State/Data track:** knowledge state tracking, decay/forgetting model.
- **Person B — Agent/Logic track:** re-planning trigger logic, decision logging, idempotency tests.
- _Dependency note:_ these tracks run mostly in parallel until wired together at phase end.

### Phase 3 (stretch goal)

- **Person A — Extraction track:** source selection, legal/ToS check, LLM extraction pipeline.
- **Person B — Review/Governance track:** human-in-the-loop review interface, merge pipeline, cycle-detection re-runs.
- _Dependency note:_ B's review interface can be built/tested against fake candidate edges before A's real pipeline is done.

### Phase 4

- **Person A — Infra track (can start as early as Phase 1):** EC2 launch, Security Group config, SSH setup, Neo4j placement decision, AWS Budgets alert (set up early).
- **Person B — Deployment/CI track:** Docker/`systemd` setup, GitHub Actions CI then CD, reverse proxy/HTTPS if doing the polish step.
- _Recommendation:_ whoever is more comfortable with Linux/networking should lean toward Infra — with roughly even skill levels, this is genuinely a coin-flip; pick based on interest.

### Phase 5 (Both, together)

- Architecture diagram — split (one draws data flow, one writes explanation) or whoever is stronger visually.
- README — write together or split sections.
- Demo video — whoever is more comfortable presenting/recording; the other preps the demo script.
- Novelty-verification write-up — done together, since it requires agreement on what was searched and found.

### Overall thematic grouping

- **Person A leans toward:** Data/Graph (P1), State/Data (P2), Extraction (P3), Infra (P4).
- **Person B leans toward:** Logic/API (P1), Agent/Logic (P2), Review/Governance (P3), Deployment/CI (P4).

_(Team member names to be filled in once assigned — I have no basis to assign these.)_

---

## Open Questions

1. Which domain should the seed graph cover first?
2. What counts as "evidence" of learner knowledge in Phase 1 — quizzes, self-report, or platform integration?
3. Is a frontend/UI part of the MVP, or is a backend + API demo sufficient for now?
4. For Phase 3, which specific text sources are legally/practically permitted to use? (Some platforms restrict scraping in their ToS — check before building an extraction pipeline against a specific site.)
5. Do you already have an AWS account with free tier active, or is this a new account? (Affects whether the "free" assumptions in the deployment plan hold.)

---

## Roadmap Status

| Phase                          | Status      |
| ------------------------------ | ----------- |
| Phase 0 — Setup                | Not started |
| Phase 1 — MVP                  | Not started |
| Phase 2 — Adaptive Re-Planning | Not started |
| Phase 3 — Extraction (stretch) | Not started |
| Phase 4 — AWS EC2 Deployment   | Not started |
| Phase 5 — Portfolio Polish     | Not started |

_(Update this table as work progresses.)_

---

## Novelty Verification

There is no verified source confirming that no existing production system already does automated prerequisite-graph extraction combined with continuous re-planning. Before presenting this project as novel to companies or in interviews, search Google Scholar, arXiv, and Papers with Code for terms like "prerequisite relation extraction," "concept dependency graph," and "adaptive learning path planning," and fill in the findings below.

_Format to fill in:_

> "We searched for [specific terms] on [specific sources] and found the closest prior work is [specific system/paper], which differs from Kramly because [specific technical difference]."

---

## Notes, Assumptions & Things to Verify

- Free-tier limits for AWS, Neo4j Aura, GitHub Actions, and any LLM provider used in Phase 3 should be verified directly against each vendor's current pricing page.
- The decay/forgetting formula in Phase 2 is not a verified standard formula — confirm any referenced spaced-repetition algorithm (e.g., SM-2) from its original documentation before implementing.
- Library APIs referenced (Neo4j Python driver, LangGraph, graph visualization libraries, GitHub Actions deploy actions) should be checked against current official docs before writing code against them.
- The repository structure above is a proposed starting layout, not a fact about an existing codebase — adjust once concrete tooling decisions are made.
- This README is a living document and should be updated as architecture decisions are finalized (final Neo4j hosting choice, final LLM provider for Phase 3, final seed-graph domain, final team member names).

---

## License

_(To be decided by the team — e.g., MIT, Apache 2.0. Add the chosen license file to the repo root.)_
