from __future__ import annotations
import uuid
import json
import os
from dataclasses import dataclass
from typing import Any
import logging
import httpx
import aiohttp

import openai
from livekit.agents import APIConnectionError, APIStatusError, APITimeoutError, llm
from livekit.agents.llm import ToolChoice,ChatChunk,CompletionUsage, utils as llm_utils
from livekit.agents.llm.chat_context import ChatContext
from livekit.agents.llm.tool_context import FunctionTool
from livekit.agents.types import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectOptions,
    NotGivenOr,
)
from livekit.agents.utils import is_given
from openai.types.chat import (
    ChatCompletionChunk,
    ChatCompletionToolChoiceOptionParam,
    completion_create_params,
)
from openai.types.chat.chat_completion_chunk import Choice

# from .log import logger

from livekit.plugins.openai.utils import to_chat_ctx

# from .utils import AsyncAzureADTokenProvider, to_chat_ctx, to_fnc_ctx

lk_oai_debug = int(os.getenv("LK_OPENAI_DEBUG", 0))

logger = logging.getLogger("custom_llm_1")
logging.basicConfig(level=logging.INFO)


@dataclass
class _LLMOptions:
    model: str
    user: NotGivenOr[str]
    temperature: NotGivenOr[float]
    parallel_tool_calls: NotGivenOr[bool]
    tool_choice: NotGivenOr[ToolChoice]
    store: NotGivenOr[bool]
    metadata: NotGivenOr[dict[str, str]]
    max_completion_tokens: NotGivenOr[int]


class CustomLLM(llm.LLM):
    def __init__(
        self,
        *,
        model: str  = "gpt-4o",
        session_id: str,
        agent_id: str,
        api_key: NotGivenOr[str] = NOT_GIVEN,
        base_url: NotGivenOr[str] = NOT_GIVEN,
        client: openai.AsyncClient | None = None,
        user: NotGivenOr[str] = NOT_GIVEN,
        temperature: NotGivenOr[float] = NOT_GIVEN,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[ToolChoice] = NOT_GIVEN,
        store: NotGivenOr[bool] = NOT_GIVEN,
        metadata: NotGivenOr[dict[str, str]] = NOT_GIVEN,
        max_completion_tokens: NotGivenOr[int] = NOT_GIVEN,
        timeout: httpx.Timeout | None = None,
    ) -> None:
        """
        Create a new instance of OpenAI LLM.

        ``api_key`` must be set to your OpenAI API key, either using the argument or by setting the
        ``OPENAI_API_KEY`` environmental variable.
        """
        super().__init__()
        self.session_id = session_id
        self.agent_id = agent_id
        self._opts = _LLMOptions(
            model=model,
            user=user,
            temperature=temperature,
            parallel_tool_calls=parallel_tool_calls,
            tool_choice=tool_choice,
            store=store,
            metadata=metadata,
            max_completion_tokens=max_completion_tokens,
        )
        self._client = client or openai.AsyncClient(
            api_key=api_key if is_given(api_key) else None,
            base_url=base_url if is_given(base_url) else None,
            max_retries=0,
            http_client=httpx.AsyncClient(
                timeout=timeout
                if timeout
                else httpx.Timeout(connect=15.0, read=5.0, write=5.0, pool=5.0),
                follow_redirects=True,
                limits=httpx.Limits(
                    max_connections=50,
                    max_keepalive_connections=50,
                    keepalive_expiry=120,
                ),
            ),
        )

    def chat(
        self,
        *,
        chat_ctx: ChatContext,
        tools: list[FunctionTool] | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[ToolChoice] = NOT_GIVEN,
        response_format: NotGivenOr[
            completion_create_params.ResponseFormat | type[llm_utils.ResponseFormatT]
        ] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
    ) -> CustomLLMStream:
        extra = {}
        if is_given(extra_kwargs):
            extra.update(extra_kwargs)

        if is_given(self._opts.metadata):
            extra["metadata"] = self._opts.metadata

        if is_given(self._opts.user):
            extra["user"] = self._opts.user

        if is_given(self._opts.max_completion_tokens):
            extra["max_completion_tokens"] = self._opts.max_completion_tokens

        parallel_tool_calls = (
            parallel_tool_calls if is_given(parallel_tool_calls) else self._opts.parallel_tool_calls
        )
        if is_given(parallel_tool_calls):
            extra["parallel_tool_calls"] = parallel_tool_calls

        tool_choice = tool_choice if is_given(tool_choice) else self._opts.tool_choice  # type: ignore
        if is_given(tool_choice):
            oai_tool_choice: ChatCompletionToolChoiceOptionParam
            if isinstance(tool_choice, dict):
                oai_tool_choice = {
                    "type": "function",
                    "function": {"name": tool_choice["function"]["name"]},
                }
                extra["tool_choice"] = oai_tool_choice
            elif tool_choice in ("auto", "required", "none"):
                oai_tool_choice = tool_choice
                extra["tool_choice"] = oai_tool_choice

        if is_given(response_format):
            extra["response_format"] = llm_utils.to_openai_response_format(response_format)

        return CustomLLMStream(
            self,
            model=self._opts.model,
            client=self._client,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
            extra_kwargs=extra,
        )


class CustomLLMStream(llm.LLMStream):
    def __init__(
        self,
        llm: CustomLLM,
        *,
        model: str ,
        client: openai.AsyncClient,
        chat_ctx: llm.ChatContext,
        tools: list[FunctionTool],
        conn_options: APIConnectOptions,
        extra_kwargs: dict[str, Any],
    ) -> None:
        super().__init__(llm, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)
        self._model = model
        self._client = client
        self._llm = llm
        self._extra_kwargs = extra_kwargs

    async def _run(self) -> None:
        self._tool_call_id = None
        self._fnc_name = None
        self._fnc_raw_arguments = None
        self._tool_index = None

        try:
            # Extract last user message from chat context
            # print(f"printing chat_ctx: {self._chat_ctx}")
            chat_ctx = to_chat_ctx(self._chat_ctx, id(self._llm))
            logger.info(f"DEBUG chat_ctx: {chat_ctx}")
            if not chat_ctx:
                return

            has_assistant_spoken = any(msg["role"] == "assistant" for msg in chat_ctx)

            if has_assistant_spoken:
                # Only include user messages after last assistant
                last_assistant_idx = max(
                    (i for i, msg in enumerate(chat_ctx) if msg["role"] == "assistant" and msg.get("content", "").strip()),
                    default=-1
                )
                user_input_parts = [
                    msg["content"] for msg in chat_ctx[last_assistant_idx + 1:]
                    if msg["role"] == "user"
                ]
            else:
                # First ever message — merge all user messages (even across pauses)
                user_input_parts = [
                    msg["content"] for msg in chat_ctx
                    if msg["role"] == "user"
                ]

            # user_input = "\n".join(user_input_parts).strip()
            user_input = next(
                msg["content"]
                for msg in reversed(chat_ctx)
                if msg["role"] == "user"
            )

            print(f"User Input: {user_input}")

            print("---- CHAT CONTEXT DUMP ----")
            for i, msg in enumerate(chat_ctx):
                print(f"{i} | {msg['role']} | {msg.get('content','')}")
            print("---- END CHAT CONTEXT DUMP ----")

            session_id = self._llm.session_id
            agent_id = self._llm.agent_id

            payload = {
                "user_input": user_input,
                "session_id": session_id,
                "agent_id": agent_id
            }
            headers = {
                "Content-Type": "application/json"
            }

            full_response = ""
            total_tokens = 0

            async with aiohttp.ClientSession() as session:
                logger.info(f"Sending payload to LLM: {payload}")
                async with session.post(
                        "http://localhost:8000/chat/stream/voice",
                        json=payload,
                        headers=headers,
                ) as response:
                    if response.status != 200:
                        raise APIStatusError(
                            f"API returned status code {response.status}",
                            status_code=response.status,
                            request_id=session_id,
                            body=await response.text()
                        )

                    logger.info(f"LLM response = _______________ {str(response)}")
                    async for line in response.content:
                        # logger.info("start iterating response content")
                        if line:
                            try:
                                decoded_line = line.decode('utf-8').strip()
                                # logger.info(f"decoded_line = _______________ {decoded_line}")
                                if decoded_line.startswith('data: '):
                                    data = json.loads(decoded_line[6:])
                                    if 'content' in data:
                                        content = data['content']
                                        full_response += content
                                        total_tokens += len(content.split())
                                        chunk = llm.ChatChunk(
                                            id=session_id,
                                            delta=llm.ChoiceDelta(
                                                role="assistant",
                                                content=content,
                                            ),
                                        )
                                        # logger.info(f"chunk = _______________ {chunk}")
                                        self._event_ch.send_nowait(chunk)

                            except json.JSONDecodeError:
                                logger.info(f"chunk = _______________ {chunk}")
                            except Exception as e:
                                print(f"Error processing stream chunk: {e}")
                                logger.info(f"chunk = _______________ {chunk}")

            # Send final chunk with usage information
            final_chunk = ChatChunk(
                id=session_id,
                usage=CompletionUsage(
                    completion_tokens=total_tokens,
                    prompt_tokens = len(user_input.split()),
                    total_tokens=total_tokens + len(user_input.split())
                )
            )
            logger.info(f"chunk = _______________ {chunk}")
            self._event_ch.send_nowait(final_chunk)
            
        except httpx.TimeoutException:
            raise APITimeoutError(retryable=False) from None
        except httpx.HTTPStatusError as e:
            raise APIStatusError(
                str(e),
                status_code=e.response.status_code,
                request_id=None,
                body=e.response.text,
                retryable=False,
            ) from None
        except Exception as e:
            raise APIConnectionError(retryable=False) from e

    def _parse_choice(self, id: str, choice: Choice) -> llm.ChatChunk | None:
        delta = choice.delta

        # https://github.com/livekit/agents/issues/688
        # the delta can be None when using Azure OpenAI (content filtering)
        if delta is None:
            return None

        if delta.tool_calls:
            for tool in delta.tool_calls:
                if not tool.function:
                    continue

                call_chunk = None
                if self._tool_call_id and tool.id and tool.index != self._tool_index:
                    call_chunk = llm.ChatChunk(
                        id=id,
                        delta=llm.ChoiceDelta(
                            role="assistant",
                            content=delta.content,
                            tool_calls=[
                                llm.FunctionToolCall(
                                    arguments=self._fnc_raw_arguments or "",
                                    name=self._fnc_name or "",
                                    call_id=self._tool_call_id or "",
                                )
                            ],
                        ),
                    )
                    self._tool_call_id = self._fnc_name = self._fnc_raw_arguments = None

                if tool.function.name:
                    self._tool_index = tool.index
                    self._tool_call_id = tool.id
                    self._fnc_name = tool.function.name
                    self._fnc_raw_arguments = tool.function.arguments or ""
                elif tool.function.arguments:
                    self._fnc_raw_arguments += tool.function.arguments  # type: ignore

                if call_chunk is not None:
                    return call_chunk

        if choice.finish_reason in ("tool_calls", "stop") and self._tool_call_id:
            call_chunk = llm.ChatChunk(
                id=id,
                delta=llm.ChoiceDelta(
                    role="assistant",
                    content=delta.content,
                    tool_calls=[
                        llm.FunctionToolCall(
                            arguments=self._fnc_raw_arguments or "",
                            name=self._fnc_name or "",
                            call_id=self._tool_call_id or "",
                        )
                    ],
                ),
            )
            self._tool_call_id = self._fnc_name = self._fnc_raw_arguments = None
            return call_chunk

        return llm.ChatChunk(
            id=id,
            delta=llm.ChoiceDelta(content=delta.content, role="assistant"),
        )
