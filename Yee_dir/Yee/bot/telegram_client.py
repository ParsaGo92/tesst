from typing import Optional
from pyrogram import Client

_shared_client: Optional[Client] = None

def set_shared_client(client: Client):
    global _shared_client
    _shared_client = client

def get_shared_client() -> Optional[Client]:
    return _shared_client

def has_client() -> bool:
    return _shared_client is not None
