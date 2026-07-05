"""
load_graph.py
Person A — Phase 1: loads skills.csv and prerequisites.csv into Neo4j.

IMPORTANT — VERIFY BEFORE RUNNING:
I am not 100% certain the exact method signatures below (GraphDatabase.driver,
session.run, driver.verify_connectivity, session.execute_write) match the
CURRENT version of the official `neo4j` Python driver package, since these
have changed across major driver versions. Before running this, check:
  https://neo4j.com/docs/api/python-driver/current/
and confirm these calls still match. If `execute_write` raises an
AttributeError on your installed version, the older equivalent has been
`write_transaction` in some past versions — verify which applies to you.

Install (verify current package name/version yourself):
    pip install neo4j
"""

import csv
import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

# Load .env from project root — use abspath so path resolves correctly
# regardless of where this script is called from.
_here = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_here, "..", ".env"))

# --- Connection config ---
# Never commit real credentials. Use environment variables or a .env file
# (excluded via .gitignore) instead of hardcoding these.
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")

if not NEO4J_PASSWORD:
    raise RuntimeError("Set NEO4J_PASSWORD as an environment variable before running this script.")

# NOTE: this script is now the LEGACY single-file loader, kept for reference.
# For the actual 5-domain seed data (coding/sde/webdev/devops/aiml), use
# load_all_domains.py instead — it handles per-domain files and optional
# cross-domain merging. This script still points at the original placeholder
# example data.
SKILLS_CSV = os.path.join(os.path.dirname(__file__), "seed_data", "legacy_placeholder_example_skills.csv")
PREREQS_CSV = os.path.join(os.path.dirname(__file__), "seed_data", "legacy_placeholder_example_prerequisites.csv")


def load_skills(tx, skills):
    """
    Merges Skill nodes (MERGE, not CREATE, so re-running this script is
    idempotent and doesn't create duplicates).
    """
    query = """
    UNWIND $skills AS skill
    MERGE (s:Skill {id: skill.id})
    SET s.name = skill.name,
        s.domain = skill.domain,
        s.difficulty_level = skill.difficulty_level
    """
    tx.run(query, skills=skills)  # VERIFY: tx.run() signature against current driver docs


def load_prerequisites(tx, prereqs):
    """
    Merges PREREQUISITE_OF relationships. Assumes load_skills() already ran
    so both endpoint nodes exist.
    """
    query = """
    UNWIND $prereqs AS prereq
    MATCH (from:Skill {id: prereq.from_skill_id})
    MATCH (to:Skill {id: prereq.to_skill_id})
    MERGE (from)-[r:PREREQUISITE_OF]->(to)
    SET r.strength = prereq.strength,
        r.source = prereq.source
    """
    tx.run(query, prereqs=prereqs)


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def check_for_cycles(skills, prereqs):
    """
    Basic DFS-based cycle check BEFORE loading into Neo4j. Written from
    scratch here (not a library call) since Phase 1.3 assumes the graph
    is a DAG — a cyclic prerequisite graph would break traversal logic
    downstream.
    """
    graph = {}
    for p in prereqs:
        graph.setdefault(p["from_skill_id"], []).append(p["to_skill_id"])

    visited, in_progress = set(), set()

    def dfs(node):
        if node in in_progress:
            return True
        if node in visited:
            return False
        in_progress.add(node)
        for neighbor in graph.get(node, []):
            if dfs(neighbor):
                return True
        in_progress.remove(node)
        visited.add(node)
        return False

    return any(dfs(skill["id"]) for skill in skills)


def main():
    skills = read_csv(SKILLS_CSV)
    prereqs = read_csv(PREREQS_CSV)

    print(f"Loaded {len(skills)} skills and {len(prereqs)} prerequisite edges from CSV.")

    if check_for_cycles(skills, prereqs):
        print("WARNING: Cycle detected in prerequisite data. Fix this before loading — "
              "a cyclic graph will break the Phase 1.3 traversal/optimizer logic.")
        return

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()  # VERIFY: exists/behaves this way in your driver version
    except Exception as e:
        print(f"Could not connect to Neo4j: {e}")
        print("Check NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD and that Neo4j is running.")
        return

    with driver.session() as session:
        session.execute_write(load_skills, skills)  # VERIFY: execute_write vs write_transaction
        session.execute_write(load_prerequisites, prereqs)

    driver.close()
    print("Graph loaded. Open Neo4j Browser and run:")
    print("  MATCH (s:Skill)-[r:PREREQUISITE_OF]->(t:Skill) RETURN s, r, t")
    print("to visually confirm the structure before anyone builds against it.")


if __name__ == "__main__":
    main()