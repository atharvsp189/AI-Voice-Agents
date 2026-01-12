import os
import json
import time
import logging
import argparse
import threading
import requests

from dotenv import load_dotenv
from deepgram import DeepgramClient
from deepgram.core.events import EventType
from deepgram.extensions.types.sockets import (
    AgentV1Agent,
    AgentV1AudioConfig,
    AgentV1AudioInput,
    AgentV1AudioOutput,
    AgentV1DeepgramSpeakProvider,
    AgentV1Listen,
    AgentV1ListenProvider,
    AgentV1SettingsMessage,
    AgentV1SocketClientResponse,
    AgentV1SpeakProviderConfig,
    AgentV1Think,
    AgentV1OpenAiThinkProvider,
    # AgentV1CustomThinkProvider,
)

# -------------------------------------------------------------------
# ENV + LOGGING
# -------------------------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("voice-agent-cli")

# -------------------------------------------------------------------
# WAV HEADER
# -------------------------------------------------------------------
def create_wav_header(sample_rate=24000, bits_per_sample=16, channels=1):
    byte_rate = sample_rate * channels * (bits_per_sample // 8)
    block_align = channels * (bits_per_sample // 8)

    header = bytearray(44)
    header[0:4] = b"RIFF"
    header[8:12] = b"WAVE"
    header[12:16] = b"fmt "
    header[16:20] = (16).to_bytes(4, "little")
    header[20:22] = (1).to_bytes(2, "little")
    header[22:24] = channels.to_bytes(2, "little")
    header[24:28] = sample_rate.to_bytes(4, "little")
    header[28:32] = byte_rate.to_bytes(4, "little")
    header[32:34] = block_align.to_bytes(2, "little")
    header[34:36] = bits_per_sample.to_bytes(2, "little")
    header[36:40] = b"data"
    return header


# -------------------------------------------------------------------
# MAIN APP
# -------------------------------------------------------------------
def run_agent(audio_url: str, llm_url: str):
    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPGRAM_API_KEY not set")

    logger.info("Initializing Deepgram client")
    client = DeepgramClient(api_key=api_key)

    with client.agent.v1.connect() as connection:
        logger.info("WebSocket connected")

        # ------------------------------------------------------------
        # AGENT SETTINGS (CUSTOM LLM)
        # ------------------------------------------------------------
        settings = AgentV1SettingsMessage(
            audio=AgentV1AudioConfig(
                input=AgentV1AudioInput(
                    encoding="linear16",
                    sample_rate=24000,
                ),
                output=AgentV1AudioOutput(
                    encoding="linear16",
                    sample_rate=24000,
                    container="wav",
                ),
            ),
            agent=AgentV1Agent(
                language="en",
                greeting="Hello! How can I help you today?",
                listen=AgentV1Listen(
                    provider=AgentV1ListenProvider(
                        type="deepgram",
                        model="nova-3",
                    )
                ),
                think=AgentV1Think(
                    provider=AgentV1OpenAiThinkProvider(
                        type="open_ai",
                        model="gpt-4o-mini",   # SDK requires a known literal
                        temperature=0.7,
                    ),
                    endpoint={
                        "url": "http://localhost:8000/chat/stream/voice",
                        "headers": {
                            "Content-Type": "application/json",
                        },
                    },
                    prompt="You are a helpful assistant.",
                ),
                speak=AgentV1SpeakProviderConfig(
                    provider=AgentV1DeepgramSpeakProvider(
                        type="deepgram",
                        model="aura-2-thalia-en",
                    )
                ),
                greeting="Hello! How can I help you today?",
            ),
        )

        audio_buffer = bytearray()
        file_counter = 0
        done = False

        def on_open(event):
            print("Connection opened")

        def on_message(msg: AgentV1SocketClientResponse):
            nonlocal audio_buffer, file_counter, done

            if isinstance(msg, bytes):
                audio_buffer.extend(msg)
                print(f"Received audio data: {len(msg)} bytes")
                return

            event_type = getattr(msg, "type", "")
            logger.info(f"Event: {event_type}")

            if event_type == "AgentStartedSpeaking":
                audio_buffer.clear()

            elif event_type == "AgentAudioDone":
                filename = f"output-{file_counter}.wav"
                with open(filename, "wb") as f:
                    f.write(create_wav_header())
                    f.write(audio_buffer)
                logger.info(f"Saved {filename}")
                audio_buffer.clear()
                file_counter += 1
                done = True
            
            elif event_type == "Error":
                logger.error(f"Deepgram error: {msg}")
                done = True

        def on_error(err):
            logger.error(err)

        connection.on(EventType.OPEN, on_open)
        connection.on(EventType.MESSAGE, on_message)
        connection.on(EventType.ERROR, on_error)

        logger.info("Sending agent settings")
        connection.send_settings(settings)

        threading.Thread(
            target=connection.start_listening,
            daemon=True,
        ).start()

        time.sleep(1)

        # ------------------------------------------------------------
        # STREAM AUDIO
        # ------------------------------------------------------------
        logger.info(f"Streaming audio from {audio_url}")
        response = requests.get(audio_url, stream=True)
        response.raw.read(44)  # skip wav header

        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                try:
                    connection.send_media(chunk)
                except Exception as e:
                    logger.error(f"WebSocket closed while sending audio: {e}")
                    break
        logger.info("Audio streaming complete")

        start = time.time()
        while not done and time.time() - start < 30:
            time.sleep(1)

        if not done:
            logger.warning("Timeout waiting for agent response")
        else:
            logger.info("Conversation finished successfully")


# -------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Deepgram Voice Agent CLI")
    parser.add_argument(
        "--audio",
        default="https://dpgr.am/spacewalk.wav",
        help="Audio WAV URL",
    )
    parser.add_argument(
        "--llm-url",
        default="http://localhost:8000/v1/chat/completions",
        help="Custom LLM OpenAI-compatible endpoint",
    )
    args = parser.parse_args()

    run_agent(args.audio, args.llm_url)


if __name__ == "__main__":
    main()
