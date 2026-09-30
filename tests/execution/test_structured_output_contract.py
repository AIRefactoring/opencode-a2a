"""Structured output end-to-end (metadata.shared.format → StructuredOutput artifact).

Contract under test (hallazgos H-01/H-04, fleet F3 §7):
1. A2A request metadata `shared.format = {type: json_schema, schema: {...}}`
   is passed through to OpencodeUpstreamClient.send_message as
   format_override — retryCount is stripped client-side (H-03).
2. When the upstream response carries a tool part named StructuredOutput
   with state.input = {object}, the coordinator emits an extra artifact
   named "structured_output" containing the JSON.
"""

from __future__ import annotations

from typing import Any

import pytest
from a2a.types import Part, TaskState

from opencode_a2a.execution.executor import OpencodeAgentExecutor
from opencode_a2a.opencode_upstream_client import OpencodeMessage
from tests.support.helpers import DummyEventQueue, make_request_context_with_parts
from tests.support.settings import make_settings


class StructuredOutputClient:
    """Records send_message kwargs; replies with a StructuredOutput tool part."""

    def __init__(self, *, with_structured: bool) -> None:
        self.stream_timeout = None
        self.directory = "/tmp/workspace"
        self.settings = make_settings(
            test_bearer_token="test",
            opencode_base_url="http://localhost",
        )
        self.sent_format: list[dict[str, Any] | None] = []
        self._with_structured = with_structured

    async def close(self) -> None:
        return None

    async def create_session(
        self, title: str | None = None, *, directory: str | None = None
    ) -> str:
        del title, directory
        return "ses-1"

    async def send_message(
        self,
        session_id: str,
        text: str | None = None,
        *,
        parts: list[dict[str, Any]] | None = None,
        directory: str | None = None,
        workspace_id: str | None = None,
        model_override: dict[str, str] | None = None,
        timeout_override=None,  # noqa: ANN001
        format_override: dict[str, Any] | None = None,
    ) -> OpencodeMessage:
        del directory, workspace_id, model_override, timeout_override
        self.sent_format.append(format_override)
        raw: dict[str, Any] = {"parts": [{"type": "text", "text": "done"}]}
        if self._with_structured:
            raw["parts"].append(
                {
                    "type": "tool",
                    "tool": "StructuredOutput",
                    "state": {
                        "status": "done",
                        "input": {"fleet.summary": "hecho", "fleet.diff": ""},
                    },
                }
            )
        return OpencodeMessage(
            text="done", session_id=session_id, message_id="msg-1", raw=raw
        )

    async def stream_events(self, stop_event=None, *, directory: str | None = None):  # noqa: ANN001
        del stop_event, directory
        for _ in ():
            yield {}

    async def remember_interrupt_request(self, **_kwargs) -> None:
        return None

    async def resolve_interrupt_request(self, request_id: str):
        del request_id
        return "missing", None

    async def resolve_interrupt_session(self, request_id: str) -> str | None:
        del request_id
        return None

    async def discard_interrupt_request(self, request_id: str) -> None:
        del request_id


SCHEMA = {
    "type": "object",
    "properties": {"fleet.summary": {"type": "string"}, "fleet.diff": {"type": "string"}},
    "required": ["fleet.summary", "fleet.diff"],
    "additionalProperties": False,
}


def _metadata_format() -> dict[str, Any]:
    return {
        "shared": {
            "format": {"type": "json_schema", "schema": SCHEMA, "retryCount": 3}
        }
    }


def _artifact_names(queue) -> list[str]:
    names: list[str] = []
    for event in queue.events:
        task = getattr(event, "artifact", None)
        if task is not None:
            names.append(event.artifact.name)
            continue
        # non-streaming coordinator enqueues a final Task with artifacts
        for artifact in getattr(event, "artifacts", None) or []:
            names.append(artifact.name)
    return names


def _structured_artifact(queue):
    for event in queue.events:
        for artifact in getattr(event, "artifacts", None) or []:
            if artifact.name == "structured_output":
                return artifact
        single = getattr(event, "artifact", None)
        if single is not None and single.name == "structured_output":
            return single
    return None


@pytest.mark.asyncio
async def test_format_metadata_reaches_client_without_retry_count() -> None:
    client = StructuredOutputClient(with_structured=True)
    executor = OpencodeAgentExecutor(client=client, streaming_enabled=False)
    queue = DummyEventQueue()
    context = make_request_context_with_parts(
        task_id="task-1",
        context_id="ctx-1",
        parts=[Part(text="work")],
        metadata=_metadata_format(),
    )

    await executor.execute(context, queue)

    assert client.sent_format == [
        {
            "type": "json_schema",
            "schema": SCHEMA,
        }
    ]


@pytest.mark.asyncio
async def test_structured_output_tool_part_becomes_artifact() -> None:
    client = StructuredOutputClient(with_structured=True)
    executor = OpencodeAgentExecutor(client=client, streaming_enabled=False)
    queue = DummyEventQueue()
    context = make_request_context_with_parts(
        task_id="task-1",
        context_id="ctx-1",
        parts=[Part(text="work")],
        metadata=_metadata_format(),
    )

    await executor.execute(context, queue)

    names = _artifact_names(queue)
    assert "structured_output" in names
    structured = _structured_artifact(queue)
    assert structured is not None
    # data part carries the validated JSON object (a2a_utils.make_data_part)
    from google.protobuf.json_format import MessageToDict

    payload = MessageToDict(structured.parts[0]).get("data", {})
    assert payload == {"fleet.summary": "hecho", "fleet.diff": ""}


@pytest.mark.asyncio
async def test_no_structured_part_keeps_only_response_artifact() -> None:
    client = StructuredOutputClient(with_structured=False)
    executor = OpencodeAgentExecutor(client=client, streaming_enabled=False)
    queue = DummyEventQueue()
    context = make_request_context_with_parts(
        task_id="task-1",
        context_id="ctx-1",
        parts=[Part(text="work")],
        metadata=_metadata_format(),
    )

    await executor.execute(context, queue)

    assert "structured_output" not in _artifact_names(queue)
    assert "response" in _artifact_names(queue)


@pytest.mark.asyncio
async def test_invalid_format_metadata_is_ignored() -> None:
    client = StructuredOutputClient(with_structured=True)
    executor = OpencodeAgentExecutor(client=client, streaming_enabled=False)
    queue = DummyEventQueue()
    context = make_request_context_with_parts(
        task_id="task-1",
        context_id="ctx-1",
        parts=[Part(text="work")],
        metadata={"shared": {"format": {"type": "text"}}},
    )

    await executor.execute(context, queue)

    assert client.sent_format == [None]
    assert queue.events[-1].status.state == TaskState.TASK_STATE_COMPLETED