import os
from pyexpat import model
from typing import Dict

from dotenv import load_dotenv
load_dotenv()

from llama_index.core import VectorStoreIndex
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.core.llms import ChatMessage
from llama_index.llms.openai import OpenAI
from llama_index.core.chat_engine import SimpleChatEngine

from chat_history_handler import load_chat_history, save_chat_history

# LLM
llm = OpenAI(
    model="gpt-4o-mini",
    api_key=os.getenv("OPENAI_API_KEY"),
    streaming=True,
)

print("LLM initialized with model:", model)

# In Memory Session Storage
session_memory: Dict[str, ChatMemoryBuffer] = {}
session_engines = {}

def get_chat_engine(session_id: str):
    if session_id not in session_memory:
        # Load previous history 
        history = load_chat_history(session_id)
        # convert to the format that llamaindex expects
        memory = ChatMemoryBuffer.from_defaults(
            chat_history=history,
            token_limit=4000
            )

        index = VectorStoreIndex.from_documents([])

        chat_engine = SimpleChatEngine.from_defaults(
            llm=llm,
            memory=memory,
            chat_mode="context"
        )

        session_memory[session_id] = memory
        session_engines[session_id] = chat_engine

    return session_engines[session_id]

def stream_chat_response(session_id: str, user_message: str):
    # generaor to stream chat response
    chat_engine = get_chat_engine(session_id)
    response = chat_engine.stream_chat(user_message)
    assistant_reply = []

    print("DEBUG: response object =", response)

    for token in response.response_gen:
        print("TOKEN:", repr(token))
        assistant_reply.append(token)
        yield token
    
    full_response = "".join(assistant_reply)
    memory = session_memory[session_id]
    save_chat_history(session_id, memory.get())