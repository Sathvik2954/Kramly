import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from main import app
from app.database import get_driver, init_driver, close_driver

client = TestClient(app)

def test_marketplace_override_api_flow():
    init_driver()
    driver = get_driver()
    
    # 1. Cleanup
    with driver.session() as session:
        session.run("MATCH (a:Author {id: 'auth_test_999'}) DETACH DELETE a")
        session.run("MATCH (r:Resource) WHERE r.author_id = 'auth_test_999' DETACH DELETE r")
        session.run("MERGE (s:Skill {id: 'SKILL_TEST_999'}) SET s.name = 'Test Skill'")

    try:
        # 2. Register resource via POST /marketplace/resources
        payload = {
            "resource_id": "res_test_999",
            "title": "Learning Test Skill",
            "description": "This note explains the core concepts of Test Skill.",
            "author": "auth_test_999",
            "covered_skills": ["SKILL_TEST_999"],
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        response = client.post("/marketplace/resources", json=payload)
        assert response.status_code == 201
        res_json = response.json()
        assert res_json["resource_id"] == "res_test_999"
        assert res_json["title"] == "Learning Test Skill"
        assert "SKILL_TEST_999" in res_json["covered_skills"]
        
        # 3. Retrieve resource via GET /marketplace/resources/{resource_id}
        get_response = client.get("/marketplace/resources/res_test_999")
        assert get_response.status_code == 200
        get_json = get_response.json()
        assert get_json["title"] == "Learning Test Skill"
        assert get_json["author"] == "auth_test_999"
        
        # 4. Fetch recommendations via GET /marketplace/resources?skill_id=SKILL_TEST_999
        rec_response = client.get("/marketplace/resources?skill_id=SKILL_TEST_999")
        assert rec_response.status_code == 200
        rec_list = rec_response.json()
        assert len(rec_list) >= 1
        assert rec_list[0]["resource_id"] == "res_test_999"
        assert "Recommended" in rec_list[0]["reason"]

        # 5. Test rating endpoint
        rate_response = client.post("/marketplace/resource/res_test_999/rate?author_id=auth_test_999&rating=4.5")
        assert rate_response.status_code == 200
        rate_json = rate_response.json()
        assert rate_json["status"] == "success"

        # 6. Test evolution: Register a new resource and supersede the old one
        payload_new = {
            "resource_id": "res_test_888",
            "title": "Learning Test Skill v2",
            "description": "This is a newer, improved note explaining Test Skill.",
            "author": "auth_test_999",
            "covered_skills": ["SKILL_TEST_999"],
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        reg_new_res = client.post("/marketplace/resources", json=payload_new)
        assert reg_new_res.status_code == 201

        supersede_res = client.post("/marketplace/resource/res_test_999/supersede?new_resource_id=res_test_888")
        assert supersede_res.status_code == 200

        # Verify history
        history_res = client.get("/marketplace/resource/res_test_888/history")
        assert history_res.status_code == 200
        history_json = history_res.json()
        assert len(history_json["history"]) >= 1
        assert history_json["history"][0]["id"] == "res_test_999"
        assert history_json["history"][0]["status"] == "outdated"
        
    finally:
        # Cleanup
        with driver.session() as session:
            session.run("MATCH (a:Author {id: 'auth_test_999'}) DETACH DELETE a")
            session.run("MATCH (r:Resource) WHERE r.author_id = 'auth_test_999' DETACH DELETE r")
            session.run("MATCH (s:Skill {id: 'SKILL_TEST_999'}) DETACH DELETE s")
        close_driver()
