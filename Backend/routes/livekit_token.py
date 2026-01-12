from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from livekit import api
from fastapi import Request
import os
import time
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=dotenv_path)

router = APIRouter()

API_KEY = os.getenv("LIVEKIT_API_KEY")
API_SECRET = os.getenv("LIVEKIT_API_SECRET")
LIVEKIT_URL = os.getenv("LIVEKIT_URL")

@router.get("/connection-details")
def get_connection_details(request: Request, session_id: str, agent_id: str):
    if not API_KEY or not API_SECRET or not LIVEKIT_URL:
        raise HTTPException(status_code=500, detail="Missing LiveKit env variables")

    # room_name = f"{session_id}"
    room_name = f"{session_id}::{agent_id}"
    print("Room Name: ", room_name)
    identity = f"user_{session_id}"

    token = api.AccessToken(API_KEY, API_SECRET) \
        .with_identity(identity) \
        .with_name("AI Agent User") \
        .with_grants(api.VideoGrants(
            room_join=True,
            room=room_name,
            can_subscribe=True,
            can_publish=True,
            can_publish_data=True
        ))

    return JSONResponse({
        "serverUrl": LIVEKIT_URL,
        "roomName": room_name,
        "participantToken": token.to_jwt(),
        "participantName": identity
    })