import json
import os
from typing import List
from llama_index.core.llms import ChatMessage

STORE_DIR = "chat_store"
os.makedirs(STORE_DIR, exist_ok=True)


def session_file(session_id: str) -> str:
    return os.path.join(STORE_DIR, f"{session_id}.json")

def load_chat_history(session_id: str) -> List[ChatMessage]:
    path = session_file(session_id)

    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return [
        ChatMessage(role=m["role"], content=m["content"])
        for m in data.get("messages", [])
    ]

def save_chat_history(session_id: str, messages: List[ChatMessage]):
    path = session_file(session_id)

    data = {
        "session_id": session_id,
        "messages": [
            {"role": m.role, "content": m.content}
            for m in messages
        ],
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
