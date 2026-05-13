import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from handlers.onboarding import OnboardingHandler
from handlers.event import InboundEvent
from models.models import Client

@pytest.fixture
def mock_db():
    db = AsyncMock()
    return db

@pytest.fixture
def mock_adapter():
    with patch("handlers.onboarding.get_messaging_adapter") as mock_get_adapter:
        adapter = AsyncMock()
        mock_get_adapter.return_value = adapter
        yield adapter

@pytest.fixture
def mock_redis():
    with patch("handlers.onboarding.get_onboard_state") as get_state, \
         patch("handlers.onboarding.set_onboard_state") as set_state, \
         patch("handlers.onboarding.clear_onboard_state") as clear_state:
        yield get_state, set_state, clear_state

@pytest.mark.asyncio
async def test_first_contact_creates_client(mock_db, mock_adapter, mock_redis):
    get_state, set_state, clear_state = mock_redis
    
    event = InboundEvent(provider="whatsapp", sender_phone="123", message_text="hello")
    event.client = None # New client

    response = await OnboardingHandler.handle(event, mock_db)
    
    assert response.status_code == 200
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()
    
    # Should ask for consent
    mock_adapter.send_interactive_message.assert_called_once()
    assert "Would you like to receive product updates" in mock_adapter.send_interactive_message.call_args[1]["body"]
    set_state.assert_called_with("123", "awaiting_consent")

@pytest.mark.asyncio
async def test_consent_yes_moves_to_language(mock_db, mock_adapter, mock_redis):
    get_state, set_state, clear_state = mock_redis
    get_state.return_value = "awaiting_consent"
    
    client = Client(phone="123", opted_in=False)
    event = InboundEvent(provider="whatsapp", sender_phone="123", button_payload="consent_yes")
    event.client = client

    response = await OnboardingHandler.handle(event, mock_db)
    
    assert response.status_code == 200
    assert client.opted_in is True
    set_state.assert_called_with("123", "awaiting_language")
    
    # Should ask for language
    mock_adapter.send_interactive_message.assert_called_once()
    assert "What language do you prefer" in mock_adapter.send_interactive_message.call_args[1]["body"]

@pytest.mark.asyncio
async def test_language_moves_to_name(mock_db, mock_adapter, mock_redis):
    get_state, set_state, clear_state = mock_redis
    get_state.return_value = "awaiting_language"
    
    client = Client(phone="123", opted_in=True)
    event = InboundEvent(provider="whatsapp", sender_phone="123", button_payload="lang_en")
    event.client = client

    response = await OnboardingHandler.handle(event, mock_db)
    
    assert response.status_code == 200
    assert client.language == "en"
    set_state.assert_called_with("123", "awaiting_name")
    
    mock_adapter.send_message.assert_called_once()
    assert "what's your name" in mock_adapter.send_message.call_args[1]["message"].lower()

@pytest.mark.asyncio
@patch("handlers.onboarding.menu_service")
async def test_name_completes_onboarding(mock_menu_service, mock_db, mock_adapter, mock_redis):
    get_state, set_state, clear_state = mock_redis
    get_state.return_value = "awaiting_name"
    mock_menu_service.send_main_menu = AsyncMock()
    
    client = Client(phone="123", language="en")
    event = InboundEvent(provider="whatsapp", sender_phone="123", message_text="John Doe")
    event.client = client

    response = await OnboardingHandler.handle(event, mock_db)
    
    assert response.status_code == 200
    assert client.name == "John Doe"
    clear_state.assert_called_once_with("123")
    
    mock_adapter.send_message.assert_called_once()
    assert "John Doe" in mock_adapter.send_message.call_args[1]["message"]
    mock_menu_service.send_main_menu.assert_called_once()
