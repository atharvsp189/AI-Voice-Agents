import os
import threading
import pyaudio

from deepgram import DeepgramClient
from deepgram.core.events import EventType
from deepgram.extensions.types.sockets import ListenV1SocketClientResponse

from dotenv import load_dotenv
load_dotenv()
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")

RATE = 16000
CHANNELS = 1
FORMAT = pyaudio.paInt16
CHUNK = 1024


def main():
    if not DEEPGRAM_API_KEY:
        raise RuntimeError("DEEPGRAM_API_KEY not set")

    deepgram = DeepgramClient(api_key=DEEPGRAM_API_KEY)

    with deepgram.listen.v1.connect(
        model="nova-3",
        encoding="linear16",
        sample_rate=RATE,
        channels=CHANNELS,
    ) as connection:

        def on_message(message: ListenV1SocketClientResponse):
            if hasattr(message, "channel"):
                alternatives = message.channel.alternatives
                if alternatives and alternatives[0].transcript:
                    print(alternatives[0].transcript)

        connection.on(EventType.OPEN, lambda _: print("🎙️ Connection opened"))
        connection.on(EventType.MESSAGE, on_message)
        connection.on(EventType.CLOSE, lambda _: print("🔌 Connection closed"))
        connection.on(EventType.ERROR, lambda e: print(f"❌ Error: {e}"))

        # Start websocket listener
        listener_thread = threading.Thread(target=connection.start_listening)
        listener_thread.start()

        # Setup microphone
        audio = pyaudio.PyAudio()
        stream = audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )

        print("🎧 Speak into the microphone (Press ENTER to stop)")

        try:
            while True:
                data = stream.read(CHUNK, exception_on_overflow=False)
                connection.send_media(data)
        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f"Mic error: {e}")

        input("\nPress ENTER to exit...\n")

        # Cleanup
        stream.stop_stream()
        stream.close()
        audio.terminate()
        connection.finish()

        listener_thread.join(timeout=3)
        print("✅ Finished")


if __name__ == "__main__":
    main()
