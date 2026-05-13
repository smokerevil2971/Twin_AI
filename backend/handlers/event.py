from dataclasses import dataclass, field
from typing import Optional, Dict, Any

@dataclass
class InboundEvent:
    provider: str
    sender_phone: str
    message_text: str = ""
    media_url: str = ""
    media_type: str = ""
    button_payload: str = ""
    list_id: str = ""
    inbound_msg_id: str = ""
    base_url: str = ""
    
    is_delivery_receipt: bool = False
    delivery_status: str = ""
    delivery_msg_id: str = ""
    delivery_payload: Dict[str, Any] = field(default_factory=dict)
    
    is_owner: bool = False
    
    # We can attach the loaded client here
    client: Optional[Any] = None
