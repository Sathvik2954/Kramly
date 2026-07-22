"""
db.py
-----
Shared Neo4j connection helper for the graph/ loader scripts
(load_all_domains.py, extraction/pipeline.py).

Consolidated out of load_graph.py, load_all_domains.py, and
extraction/load_extracted.py, which each previously duplicated the same
load_dotenv + GraphDatabase.driver + verify_connectivity boilerplate.

Targets Neo4j Aura (cloud) only - no local Neo4j Desktop/Community
fallback. NEO4J_URI must be an Aura connection string
(neo4j+s://<dbid>.databases.neo4j.io), set in your .env.

VERIFY BEFORE RUNNING: driver method signatures (GraphDatabase.driver,
session.execute_write, tx.run, verify_connectivity) were checked against
Neo4j Python Driver 6.2 docs (https://neo4j.com/docs/api/python-driver/current/)
- re-verify if your installed driver version differs.
"""

import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

# Load .env from the project root (one level up from graph/), regardless of
# the caller's current working directory.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))


def get_connection_settings():
    """Reads NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD from the environment.

    Raises RuntimeError if NEO4J_URI or NEO4J_PASSWORD is unset, so scripts
    fail fast with a clear message instead of a confusing driver auth error
    or silently trying to connect to a local Desktop instance that isn't
    part of this project's setup.
    """
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER", os.environ.get("NEO4J_USERNAME", "neo4j"))
    password = os.environ.get("NEO4J_PASSWORD")

    if not uri:
        raise RuntimeError(
            "Set NEO4J_URI as an environment variable before running this script "
            "(your Neo4j Aura connection URI, e.g. neo4j+s://<db-id>.databases.neo4j.io)."
        )
    if not password:
        raise RuntimeError("Set NEO4J_PASSWORD as an environment variable before running this script.")

    return uri, user, password


def get_driver():
    """Creates and connectivity-verifies a Neo4j driver from env settings.

    Caller is responsible for closing it (`driver.close()`) when done -
    these are short-lived CLI scripts, not a long-running server process,
    so we don't manage a shared singleton here the way backend/app/database.py does.
    """
    uri, user, password = get_connection_settings()
    driver = GraphDatabase.driver(uri, auth=(user, password))
    driver.verify_connectivity()  # VERIFY: exists/behaves this way in your driver version
    return driver
