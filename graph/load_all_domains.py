"""
load_all_domains.py
Loads one or more domain seed datasets into Neo4j, optionally including
cross-domain prerequisite links.

VERIFY BEFORE RUNNING: same driver-method caveats as load_graph.py apply
here (GraphDatabase.driver, session.execute_write, tx.run, verify_connectivity).
These were checked against Neo4j Python Driver 6.2 official docs as of this
writing, but confirm against current docs if you're on a different version:
https://neo4j.com/docs/api/python-driver/current/

Usage:
    python load_all_domains.py coding sde webdev devops aiml --cross-domain
    python load_all_domains.py webdev            # just one domain
"""

import csv
import os
import sys
from dotenv import load_dotenv
from neo4j import GraphDatabase

# Load .env from project root (one level up from graph/)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")

if not NEO4J_PASSWORD:
    raise RuntimeError("Set NEO4J_PASSWORD as an environment variable before running this script.")

SEED_DIR = os.path.join(os.path.dirname(__file__), "seed_data")


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_skills(tx, skills):
    query = """
    UNWIND $skills AS skill
    MERGE (s:Skill {id: skill.id})
    SET s.name = skill.name,
        s.domain = skill.domain,
        s.difficulty_level = skill.difficulty_level
    """
    tx.run(query, skills=skills)


def load_prerequisites(tx, prereqs):
    query = """
    UNWIND $prereqs AS prereq
    MATCH (from:Skill {id: prereq.from_skill_id})
    MATCH (to:Skill {id: prereq.to_skill_id})
    MERGE (from)-[r:PREREQUISITE_OF]->(to)
    SET r.strength = prereq.strength,
        r.source = prereq.source
    """
    tx.run(query, prereqs=prereqs)


def check_for_cycles(all_skills, all_prereqs):
    """From-scratch DFS cycle check across the combined dataset — important
    when merging domains, since a cross-domain edge could introduce a cycle
    that didn't exist within any single domain."""
    graph = {}
    for p in all_prereqs:
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

    return any(dfs(skill["id"]) for skill in all_skills)


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: python load_all_domains.py <domain1> <domain2> ... [--cross-domain]")
        print("Available domains: coding, sde, webdev, devops, aiml")
        return

    include_cross = "--cross-domain" in args
    domains = [a for a in args if a != "--cross-domain"]

    all_skills, all_prereqs = [], []

    for domain in domains:
        skills_path = os.path.join(SEED_DIR, domain, f"{domain}_skills.csv")
        prereqs_path = os.path.join(SEED_DIR, domain, f"{domain}_prerequisites.csv")
        if not os.path.exists(skills_path):
            print(f"WARNING: no seed data found for domain '{domain}' — skipping.")
            continue
        all_skills.extend(read_csv(skills_path))
        all_prereqs.extend(read_csv(prereqs_path))
        print(f"Loaded {domain}: {len(read_csv(skills_path))} skills.")

    if include_cross:
        cross_path = os.path.join(SEED_DIR, "cross_domain_prerequisites.csv")
        if os.path.exists(cross_path):
            cross_prereqs = read_csv(cross_path)
            all_prereqs.extend(cross_prereqs)
            print(f"Included {len(cross_prereqs)} cross-domain prerequisite links.")

    print(f"Total: {len(all_skills)} skills, {len(all_prereqs)} prerequisite edges.")

    if not all_skills:
        print("Error: No skills loaded. Please check your domain names.")
        return

    if check_for_cycles(all_skills, all_prereqs):
        print("WARNING: Cycle detected in combined data. Fix before loading — "
              "check whether a cross-domain link introduced it.")
        return

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
    except Exception as e:
        print(f"Could not connect to Neo4j: {e}")
        return

    with driver.session() as session:
        session.execute_write(load_skills, all_skills)
        session.execute_write(load_prerequisites, all_prereqs)

    driver.close()
    print("Done. Verify in Neo4j Browser:")
    print("  MATCH (s:Skill)-[r:PREREQUISITE_OF]->(t:Skill) RETURN s, r, t")


if __name__ == "__main__":
    main()