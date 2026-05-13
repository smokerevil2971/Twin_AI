import pytest
from unittest.mock import AsyncMock, MagicMock
from services.broadcast_service import get_eligible_clients
from models.models import Client

@pytest.mark.asyncio
async def test_get_eligible_clients_filters_correctly(monkeypatch):
    from core.config import settings
    monkeypatch.setattr(settings, "broadcast_cooldown_enabled", True)
    monkeypatch.setattr(settings, "broadcast_cooldown_hours", 24)

    c1 = Client(id="uuid1", phone="111", opted_in=True, is_deleted=False)
    c2 = Client(id="uuid2", phone="222", opted_in=True, is_deleted=False)
    c3 = Client(id="uuid3", phone="333", opted_in=True, is_deleted=False)

    mock_db = AsyncMock()
    
    mock_result_1 = MagicMock()
    mock_result_1.scalars.return_value.all.return_value = [c1, c2, c3]
    
    mock_result_2 = MagicMock()
    mock_result_2.all.return_value = [("uuid2",)]
    
    # Execute will be called twice
    mock_db.execute.side_effect = [mock_result_1, mock_result_2]

    eligible = await get_eligible_clients(mock_db)
    
    assert len(eligible) == 2
    ids = [c.id for c in eligible]
    assert "uuid1" in ids
    assert "uuid3" in ids

@pytest.mark.asyncio
async def test_get_eligible_clients_override_cooldown(monkeypatch):
    from core.config import settings
    monkeypatch.setattr(settings, "broadcast_cooldown_enabled", True)
    
    c1 = Client(id="uuid1", phone="111", opted_in=True, is_deleted=False)
    
    mock_db = AsyncMock()
    mock_result_1 = MagicMock()
    mock_result_1.scalars.return_value.all.return_value = [c1]
    
    mock_db.execute.side_effect = [mock_result_1]
    
    eligible = await get_eligible_clients(mock_db, override_cooldown=True)
    
    assert len(eligible) == 1
    assert eligible[0].id == "uuid1"
