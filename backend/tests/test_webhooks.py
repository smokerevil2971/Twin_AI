import hmac
import hashlib
import json
import pytest

def test_meta_webhook_missing_signature(client, monkeypatch):
    from core.config import settings
    monkeypatch.setattr(settings, "messaging_provider", "meta")
    
    payload = {"entry": [{"changes": [{"value": {"messages": [{"from": "1234567890", "text": {"body": "hello"}}]}}]}]}
    response = client.post("/api/v1/webhooks/whatsapp", json=payload)
    
    assert response.status_code == 200
    assert response.text == "unauthorized"

def test_meta_webhook_invalid_signature(client, monkeypatch):
    from core.config import settings
    monkeypatch.setattr(settings, "messaging_provider", "meta")
    
    payload = {"entry": [{"changes": [{"value": {"messages": [{"from": "1234567890", "text": {"body": "hello"}}]}}]}]}
    headers = {"X-Hub-Signature-256": "sha256=invalid_signature"}
    response = client.post("/api/v1/webhooks/whatsapp", json=payload, headers=headers)
    
    assert response.status_code == 200
    assert response.text == "signature_invalid"

def test_meta_webhook_valid_signature(client, monkeypatch):
    from core.config import settings
    monkeypatch.setattr(settings, "messaging_provider", "meta")
    monkeypatch.setattr(settings, "meta_app_secret", "test_secret")
    
    # Use empty value payload so it returns 200 "ok" without trying to process a message
    payload = {"entry": [{"changes": [{"value": {}}]}]}
    # FastAPI test client json=... converts it without spaces. 
    # To be safe on byte-for-byte signature match, send raw content
    body_bytes = json.dumps(payload).encode('utf-8')
    
    signature = hmac.new(b"test_secret", body_bytes, hashlib.sha256).hexdigest()
    headers = {"X-Hub-Signature-256": f"sha256={signature}", "Content-Type": "application/json"}
    
    response = client.post("/api/v1/webhooks/whatsapp", content=body_bytes, headers=headers)
    
    assert response.status_code == 200
    assert response.text == "ignored"
