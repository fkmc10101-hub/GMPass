from .conftest import upload


def _seed(client):
    for name, c, t in [
        ("us_sample.txt", "US", "21 CFR 211 (test)"),
        ("eu_sample.txt", "EU", "EudraLex Vol.4 (test)"),
        ("kr_sample.txt", "KR", "의약품 제조 및 품질관리 (test)"),
    ]:
        r = upload(client, name, c, t, doc_code=t, version="test", effective_date="2026-01-01")
        assert r.status_code == 202, r.text
    docs = client.get("/api/documents").json()
    assert all(d["status"] == "indexed" for d in docs), docs
    return docs


def test_health_and_countries(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["indexed_chunks"] == 0
    codes = [c["code"] for c in client.get("/api/countries").json()]
    assert codes == ["KR", "US", "EU", "PICS", "JP", "ICH"]


def test_upload_validation_and_duplicates(client):
    assert upload(client, "us_sample.txt", "XX", "bad").status_code == 422
    assert upload(client, "us_sample.txt", "US", "t", effective_date="2026/01/01").status_code == 422
    assert upload(client, "us_sample.txt", "US", "t").status_code == 202
    dup = upload(client, "us_sample.txt", "US", "again")
    assert dup.status_code == 409


def test_document_chunks_reindex_delete(client):
    docs = _seed(client)
    kr = next(d for d in docs if d["country"] == "KR")
    chunks = client.get(f"/api/documents/{kr['id']}/chunks").json()
    assert chunks and any(c["section"].startswith("제5조") for c in chunks)
    assert client.post(f"/api/documents/{kr['id']}/reindex").json()["id"] == kr["id"]
    assert client.get(f"/api/documents/{kr['id']}").json()["status"] == "indexed"
    assert client.delete(f"/api/documents/{kr['id']}").status_code == 204
    assert client.get(f"/api/documents/{kr['id']}").status_code == 404
    assert [d["code"] for d in client.get("/api/countries").json() if d["indexed_documents"]] == ["US", "EU"]


def test_ask_single_and_compare_with_citations(client):
    _seed(client)
    r = client.post("/api/chat/ask", json={"question": "audit trail 요구사항은?", "countries": ["EU", "US"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "single" and len(body["answers"]) == 1
    a = body["answers"][0]
    assert a["citations"][0]["cited"] is True and a["citations"][0]["chunk_id"]
    assert a["review_required"] is False
    assert "retrieve:ALL" in body["timings_ms"]

    r = client.post("/api/chat/ask", json={"question": "출하 승인 주체 batch release", "countries": ["kr", "eu", "us"],
                                           "mode": "compare", "session_id": body["session_id"]})
    body2 = r.json()
    assert [a["country"] for a in body2["answers"]] == ["DIFF", "KR", "EU", "US"]
    assert body2["session_id"] == body["session_id"]

    detail = client.get(f"/api/chat/sessions/{body['session_id']}").json()
    roles = [m["role"] for m in detail["messages"]]
    assert roles == ["user", "assistant", "user"] + ["assistant"] * 4
    assert detail["messages"][1]["citations"][0]["document_title"]


def test_compare_needs_two_countries_and_unknown_code(client):
    assert client.post("/api/chat/ask", json={"question": "질문", "countries": ["EU"], "mode": "compare"}).status_code == 422
    assert client.post("/api/chat/ask", json={"question": "질문", "countries": ["ZZ"]}).status_code == 422


def test_cache_hit_and_invalidation(client, fake_generator):
    _seed(client)
    q = {"question": "변경관리 절차", "countries": ["KR"]}
    first = client.post("/api/chat/ask", json=q).json()
    calls = fake_generator.calls
    second = client.post("/api/chat/ask", json=q).json()
    assert second["cached"] is True and fake_generator.calls == calls
    assert second["answers"][0]["answer"] == first["answers"][0]["answer"]
    # 문서가 바뀌면(재색인) 캐시를 쓰지 않는다
    kr = next(d for d in client.get("/api/documents").json() if d["country"] == "KR")
    client.post(f"/api/documents/{kr['id']}/reindex")
    third = client.post("/api/chat/ask", json=q).json()
    assert third["cached"] is False


def test_review_flags(client, fake_generator):
    _seed(client)
    fake_generator.mode = "no_cite"
    a = client.post("/api/chat/ask", json={"question": "QP 역할", "countries": ["EU"], "use_cache": False}).json()["answers"][0]
    assert a["review_required"] and "NO_CITATION" in a["review_reasons"] and a["review_messages"]
    fake_generator.mode = "unstable"
    a = client.post("/api/chat/ask", json={"question": "QP 역할", "countries": ["EU"], "use_cache": False}).json()["answers"][0]
    assert "LOW_CONSISTENCY" in a["review_reasons"]


def test_no_documents_means_no_evidence(client):
    a = client.post("/api/chat/ask", json={"question": "아무 질문", "countries": ["JP"]}).json()["answers"][0]
    assert a["review_required"] and "NO_EVIDENCE" in a["review_reasons"]


def test_feedback_and_session_delete(client):
    _seed(client)
    body = client.post("/api/chat/ask", json={"question": "출하 승인", "countries": ["KR"]}).json()
    mid = body["answers"][0]["message_id"]
    assert client.post(f"/api/messages/{mid}/feedback", json={"rating": "up"}).status_code == 201
    assert client.post(f"/api/messages/{body['question_message_id']}/feedback", json={"rating": "up"}).status_code == 404
    assert client.get("/api/chat/sessions").json()[0]["message_count"] == 2
    assert client.delete(f"/api/chat/sessions/{body['session_id']}").status_code == 204
    assert client.get("/api/chat/sessions").json() == []


def test_search_endpoint(client):
    _seed(client)
    hits = client.post("/api/search", json={"query": "Qualified Person", "countries": ["EU"], "top_k": 2}).json()
    assert hits and all(h["country"] == "EU" for h in hits)


def test_admin_token(client):
    client.app.state.settings.admin_token = "secret"
    assert upload(client, "us_sample.txt", "US", "t").status_code == 401
    with open(__import__("tests.conftest", fromlist=["FIXTURES"]).FIXTURES / "us_sample.txt", "rb") as f:
        r = client.post("/api/documents", files={"file": ("us.txt", f)}, data={"country": "US", "title": "t"},
                        headers={"X-Admin-Token": "secret"})
    assert r.status_code == 202


def test_translate_citation_is_cached(client, fake_generator):
    _seed(client)
    a = client.post("/api/chat/ask", json={"question": "Qualified Person batch", "countries": ["EU"]}).json()["answers"][0]
    cid = a["citations"][0]["chunk_id"]
    first = client.post("/api/translate", json={"chunk_id": cid}).json()
    assert first["text_ko"].startswith("[번역]") and first["cached"] is False
    second = client.post("/api/translate", json={"chunk_id": cid}).json()
    assert second["cached"] is True and fake_generator.translations == 1
    kr = client.post("/api/chat/ask", json={"question": "출하 승인", "countries": ["KR"]}).json()["answers"][0]
    same = client.post("/api/translate", json={"chunk_id": kr["citations"][0]["chunk_id"]}).json()
    assert same["text_ko"] == same["original"] and fake_generator.translations == 1
    assert client.post("/api/translate", json={"chunk_id": 99999}).status_code == 404
