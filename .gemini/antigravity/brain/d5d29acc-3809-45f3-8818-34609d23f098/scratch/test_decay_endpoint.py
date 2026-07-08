import urllib.request
import json
import datetime
from datetime import timezone, timedelta
from neo4j import GraphDatabase

BASE_URL = "http://127.0.0.1:8000"

def post_json(endpoint, data=None):
    url = f"{BASE_URL}{endpoint}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8") if data is not None else b"",
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))

def get_json(endpoint):
    url = f"{BASE_URL}{endpoint}"
    try:
        with urllib.request.urlopen(url) as res:
            return res.status, json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))

# Test 1: Record evidence and set target for a test learner
print("Recording target and evidence...")
post_json("/learner/decay_learner/target", {"target_skill": "C003"})
post_json("/learner/decay_learner/evidence", {"skill_id": "C001", "confidence": 1.0})

# Force last_practiced to be 60 days ago in Neo4j
print("\nSimulating decay: Setting last_practiced to 60 days ago in Neo4j...")
# Hardcode auth matching .env or default
driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "Kramly@123"))
old_date = datetime.datetime.now(timezone.utc) - timedelta(days=60)
with driver.session() as session:
    session.run(
        """
        MATCH (l:Learner {id: 'decay_learner'})-[k:KNOWS]->(s:Skill {id: 'C001'})
        SET k.last_practiced = $old_date
        """,
        old_date=old_date.isoformat()
    )
driver.close()

# Trigger a decay scan now — should detect decay on C001 for decay_learner
print("\nRunning decay scan (decay simulated)...")
status, res = post_json("/decay-scan")
print(f"Status: {status}")
print(f"Result: {res}")

# Check learner state (C001 should be in decayed_skills and NOT in known_skills)
print("\nFetching learner state...")
status, state = get_json("/learner/decay_learner")
print(f"Status: {status}")
print(f"State: {state}")

# Let's check the decision log timeline to see if a SkillForgotten replanning event was logged!
print("\nFetching decision logs...")
status, history = get_json("/decision-log/decay_learner")
print(f"Status: {status}")
print(f"Latest Decision Log: {history[-1] if history else 'None'}")
