"""
load_extracted.py
-----------------
Loads reviewed and approved prerequisite edges from reviewed_approved.csv into Neo4j.
If a skill mentioned in the CSV does not exist in the database, it creates it
as a new Skill node in the "MobileAppDev" domain to ensure the edges can connect.
"""

import csv
import os
import re
from dotenv import load_dotenv
from neo4j import GraphDatabase

# Load environment credentials from the root .env
dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
load_dotenv(dotenv_path)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

APPROVED_PATH = os.path.join(os.path.dirname(__file__), "reviewed_approved.csv")
DEFAULT_DOMAIN = "MobileAppDev"


def slugify_name(name: str) -> str:
    """Generates a clean skill ID from its text name (e.g., 'Core Language' -> 'CORE_LANGUAGE')."""
    clean = re.sub(r"[^a-zA-Z0-9\s]", "", name).strip()
    return re.sub(r"\s+", "_", clean).upper()


def load_edge_tx(tx, from_name, to_name, confidence):
    # Match or Create the skills first to avoid dangling relationships
    from_id = slugify_name(from_name)
    to_id = slugify_name(to_name)

    query = """
    MERGE (s:Skill {name: $from_name})
    ON CREATE SET s.id = $from_id,
                  s.domain = $domain,
                  s.difficulty_level = 'beginner'
                  
    MERGE (t:Skill {name: $to_name})
    ON CREATE SET t.id = $to_id,
                  t.domain = $domain,
                  t.difficulty_level = 'intermediate'
                  
    MERGE (s)-[r:PREREQUISITE_OF]->(t)
    SET r.confidence = $confidence
    RETURN s.id AS from_id, t.id AS to_id
    """
    result = tx.run(
        query,
        from_name=from_name,
        from_id=from_id,
        to_name=to_name,
        to_id=to_id,
        domain=DEFAULT_DOMAIN,
        confidence=float(confidence)
    )
    return result.single()


def main():
    if not os.path.exists(APPROVED_PATH):
        print(f"[Error] Approved edges file not found at: {APPROVED_PATH}")
        print("Please run 'review_cli.py' first to approve some relationship edges.")
        return

    print(f"Connecting to Neo4j database at {NEO4J_URI}...")
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        # Verify connectivity
        driver.verify_connectivity()
    except Exception as e:
        print(f"[Error] Failed to connect to Neo4j: {e}")
        return

    with open(APPROVED_PATH, newline="", encoding="utf-8") as f:
        edges = list(csv.DictReader(f))

    if not edges:
        print("No edges found in reviewed_approved.csv. Nothing to load.")
        driver.close()
        return

    print(f"Processing {len(edges)} approved prerequisite edges...")
    loaded_count = 0
    with driver.session() as session:
        for idx, edge in enumerate(edges, 1):
            from_name = edge.get("from_skill", "").strip()
            to_name = edge.get("to_skill", "").strip()
            confidence = edge.get("confidence", "1.0")

            if not from_name or not to_name:
                print(f"Skipping row {idx}: missing from_skill or to_skill.")
                continue

            try:
                res = session.execute_write(load_edge_tx, from_name, to_name, confidence)
                if res:
                    print(f"[{idx}] Loaded: '{from_name}' ({res['from_id']}) -> '{to_name}' ({res['to_id']})")
                    loaded_count += 1
            except Exception as ex:
                print(f"[{idx}] Failed to load edge '{from_name}' -> '{to_name}': {ex}")

    driver.close()
    print(f"\n[Success] Loaded {loaded_count} prerequisite edges successfully into Neo4j.")


if __name__ == "__main__":
    main()
