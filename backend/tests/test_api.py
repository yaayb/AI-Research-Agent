import json

from fastapi.testclient import TestClient

from app.main import create_app


def test_api_end_to_end_offline():
    with TestClient(create_app()) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/research/providers").json()["search_provider"] == "offline"
        sid = client.post("/api/research/start", json={"topic": "Agent frameworks 2026", "depth": "quick"}).json()["session_id"]
        events = []
        with client.stream("GET", f"/api/research/{sid}/stream") as r:
            for line in r.iter_lines():
                if line.startswith("data:") and line.strip() != "data: {}":
                    events.append(json.loads(line[5:]))
        assert events[0]["type"] == "session_started" and events[-1]["type"] == "complete"
        res = client.get(f"/api/research/{sid}/result").json()
        assert res["status"] == "COMPLETED" and res["report"]["sources"] and res["comparison"]
        assert client.get("/api/reports").json()[0]["session_id"] == sid
        pdf = client.get(f"/api/reports/{sid}/download/pdf")
        assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
        assert client.get(f"/api/reports/{sid}/download/md").status_code == 200
        assert client.get(f"/api/reports/{sid}/download/exe").status_code == 400
        fu = client.post(f"/api/research/{sid}/followup", json={"question": "Why did sources disagree?"})
        assert fu.status_code == 200 and fu.json()["answer"]
        stats = client.get("/api/memory/stats").json()
        assert stats["total"] >= 1
        hits = client.get("/api/memory/search", params={"q": "LangGraph orchestration"}).json()
        assert hits and "score" in hits[0]
        assert client.delete(f"/api/memory/{hits[0]['id']}").json() == {"deleted": True}
        assert client.delete(f"/api/memory/{hits[0]['id']}").status_code == 404
