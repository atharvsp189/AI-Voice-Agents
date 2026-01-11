import os
import json
import asyncio
import logging
import threading
import queue
from dotenv import load_dotenv

# FastAPI Imports
from fastapi import FastAPI, WebSocket, Request, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.responses import StreamingResponse

# Deepgram Imports
from deepgram import DeepgramClient
from deepgram.core.events import EventType
from deepgram.extensions.types.sockets import ListenV1SocketClientResponse
from deepgram.extensions.types.sockets import ListenV1MediaMessage
from deepgram.extensions.types.sockets import ListenV1ControlMessage

# LLM Logic
from llm_logic import stream_chat_response

# Setup Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("VoiceAgent")

load_dotenv()
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")

app = FastAPI()

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_class=HTMLResponse)
def get(request: Request):
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

# speech to text
@app.websocket("/listen")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("Client connected to WebSocket")

    audio_queue = queue.Queue()
    stop_event = threading.Event()
    loop = asyncio.get_running_loop()

    def run_deepgram():
        try:
            logger.info("Waiting for audio from browser...")
            try:
                first_chunk = audio_queue.get(timeout=60)
            except queue.Empty:
                logger.info("No audio received. Stopping.")
                return

            client = DeepgramClient(api_key=DEEPGRAM_API_KEY)

            def send_to_browser_sync(transcript, is_final):
                asyncio.run_coroutine_threadsafe(
                    websocket.send_text(json.dumps({
                        "type": "transcript",
                        "text": transcript,
                        "is_final": is_final
                    })), loop
                )

            def on_message(message, **kwargs):
                if not hasattr(message, "channel"): return
                # print("---\nMessage received: ---\n", message)
                if message.channel and message.channel.alternatives:
                    alt = message.channel.alternatives[0]
                    # print("---\nAlt: ---\n", alt)
                    if alt.transcript:
                        logger.info(f"Heard: {alt.transcript}")
                        send_to_browser_sync(alt.transcript, message.is_final)

            logger.info("Audio received. Connecting to Deepgram...")
            with client.listen.v1.connect(model="nova-3", smart_format=True) as connection:
                
                connection.on(EventType.OPEN, lambda _: logger.info("Deepgram OPEN"))
                connection.on(EventType.MESSAGE, on_message)
                connection.on(EventType.CLOSE, lambda _: logger.info("Deepgram CLOSED"))
                connection.on(EventType.ERROR, lambda e: logger.error(f"Deepgram Error: {e}"))

                # This prevents start_listening() from blocking the audio sending loop below.
                listener_thread = threading.Thread(target=connection.start_listening)
                listener_thread.start()

                connection.send_media(ListenV1MediaMessage(first_chunk))

                while not stop_event.is_set():
                    try:
                        # send audio data
                        data = audio_queue.get(timeout=2.0)
                        connection.send_media(ListenV1MediaMessage(data))
                    
                    except queue.Empty:
                        # prevent timeout if silence is detected
                        logger.info("Sending KeepAlive...")
                        connection.send_control(ListenV1ControlMessage(type="KeepAlive"))
                        continue
                    
                    except Exception as e:
                        logger.error(f"Error sending media: {e}")
                        break

                # Cleanup when loop ends
                listener_thread.join(timeout=1)

        except Exception as e:
            logger.error(f"Thread Error: {e}")

    # Start the worker thread
    dg_thread = threading.Thread(target=run_deepgram)
    dg_thread.start()

    try:
        while True:
            data = await websocket.receive_bytes()
            audio_queue.put(data)

    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"WebSocket Error: {e}")
    finally:
        stop_event.set()
        dg_thread.join(timeout=2)
        logger.info("Session ended")

@app.get("/chat/stream")
def chat_stream(session_id: str, message: str):
    return StreamingResponse(
        stream_chat_response(session_id, message),
        media_type="text/plain"
    )