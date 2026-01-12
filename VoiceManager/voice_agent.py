import logging
from typing import Optional
from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    metrics,
    RoomInputOptions,
)
# from livekit.agents.voice_assistant import VoiceAssistant
# from livekit.agents.pipeline.pipeline_agent import VoicePipelineAgent
from custom_llm_1 import CustomLLM
from livekit.agents import (AutoSubscribe, JobContext, llm)
from livekit.agents.llm import LLMStream
from livekit.plugins import (
    # cartesia,
    openai,
    # deepgram,
    noise_cancellation,
    silero,
)
# from livekit.plugins.turn_detector.multilingual import MultilingualModel


load_dotenv(dotenv_path=".env.local")
logger = logging.getLogger("voice-agent")

import os
print("LIVEKIT_URL =", os.getenv("LIVEKIT_URL"))


class Assistant(Agent):
    def __init__(self, session_id: str, agent_id: str) -> None:
        # This project is configured to use Deepgram STT, OpenAI LLM and Cartesia TTS plugins
        # Other great providers exist like Cerebras, ElevenLabs, Groq, Play.ht, Rime, and more
        # Learn more and pick the best one for your app:
        # https://docs.livekit.io/agents/plugins
        super().__init__(
            instructions="You are a voice assistant created by LiveKit. Your interface with users will be voice. "
            "You should use short and concise responses, and avoiding usage of unpronouncable punctuation. "
            "You were created as a demo to showcase the capabilities of LiveKit's agents framework.",
            stt=openai.STT(),
            llm=CustomLLM(session_id=session_id, agent_id=agent_id),
            tts=openai.TTS(),
            # use LiveKit's transformer-based turn detector
            # turn_detection=MultilingualModel(),
        )

    async def on_enter(self):
        logger.info(" Agent has entered and should speak.")
        # The agent should be polite and greet the user when it joins :)
        # self.session.say(instructions="Hey, how can I help you today?", allow_interruptions=True)


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Wait for the first participant to connect
    participant = await ctx.wait_for_participant()
    logger.info(f"starting voice assistant for participant {participant.identity}")

    usage_collector = metrics.UsageCollector()

    # Log metrics and collect usage data
    # def on_metrics_collected(event):
    #     print(f"Event Type: {type(event)}")
    #     print(f"Metrics event data: {event}")
    #     agent_metrics = event.agent_metrics
    #     usage_collector.collect(agent_metrics)
    #     if not hasattr(event, "agent_metrics"):
    #         logger.warning("metrics_collected event missing agent_metrics")
    #         return

    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        # minimum delay for endpointing, used when turn detector believes the user is done with their turn
        min_endpointing_delay=0.5,
        # maximum delay for endpointing, used when turn detector does not believe the user is done with their turn
        max_endpointing_delay=5.0,
    )

    # Trigger the on_metrics_collected function when metrics are collected
    # session.on("metrics_collected", on_metrics_collected)

    room_name = ctx.room.name
    session_id, agent_id = room_name.split("::", 1)
    print(f"Creating Agent for Voice Agent with agent_id: {agent_id} and session_id: {session_id}")

    assistant = Assistant(session_id=session_id, agent_id=agent_id)

    await session.start(
        room=ctx.room,
        agent=assistant,
        room_input_options=RoomInputOptions(
            # enable background voice & noise cancellation, powered by Krisp
            # included at no additional cost with LiveKit Cloud
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        ),
    )