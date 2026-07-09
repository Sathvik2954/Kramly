import os
import pytest
from fastapi.testclient import TestClient
from main import app
from app.database import get_driver, init_driver, close_driver

client = TestClient(app)

def test_marketplace_api_flow():
    init_driver()
    # 1. Clean up any existing test resources in Neo4j
    driver = get_driver()
    with driver.session() as session:
        session.run("MATCH (a:Author {id: 'test_author_1'}) DETACH DELETE a")
        session.run("MATCH (r:Resource) WHERE r.author_id = 'test_author_1' DETACH DELETE r")
        # Ensure a test skill exists in the graph to test concept extraction matching
        session.run("MERGE (s:Skill {id: 'TEST_SKILL_1'}) SET s.name = 'Docker'")

    try:
        # 2. Upload resource
        payload = {
            "title": "Introduction to Docker",
            "resource_type": "note",
            "author_id": "test_author_1",
            "allow_duplicate": True
        }
        # Simulate file upload
        file_content = b"This educational note covers Docker containerization concepts."
        files = {"file": ("docker_note.txt", file_content, "text/plain")}
        
        response = client.post("/marketplace/resource", data=payload, files=files)
        assert response.status_code == 200
        res_json = response.json()
        assert res_json["status"] == "success"
        assert "resource_id" in res_json
        assert "storage_key" in res_json
        
        resource_id = res_json["resource_id"]
        
        # 3. Retrieve resource
        get_resp = client.get(f"/marketplace/resource/{resource_id}")
        assert get_resp.status_code == 200
        get_json = get_resp.json()
        
        # Verify metadata
        metadata = get_json["metadata"]
        assert metadata["title"] == "Introduction to Docker"
        assert metadata["type"] == "note"
        assert metadata["author_id"] == "test_author_1"
        assert len(metadata["covered_skills"]) >= 1
        matched_ids = {s["skill_id"] for s in metadata["covered_skills"]}
        assert len(matched_ids) >= 1
        
        # Verify contents
        assert get_json["content"] == "This educational note covers Docker containerization concepts."
        
    finally:
        # Cleanup
        with driver.session() as session:
            session.run("MATCH (a:Author {id: 'test_author_1'}) DETACH DELETE a")
            session.run("MATCH (r:Resource) WHERE r.author_id = 'test_author_1' DETACH DELETE r")
            session.run("MATCH (s:Skill {id: 'TEST_SKILL_1'}) DETACH DELETE s")
        close_driver()
