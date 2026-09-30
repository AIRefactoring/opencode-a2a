# Structured Output Support in OpenCode A2A Adapter

## Overview
This enhancement enables JSON Schema-validated output from upstream OpenCode models when sending messages via A2A (`SendMessage`).

Previously, while the upstream OpenCode server (v2) supported structured JSON schema enforcement, the A2A adapter lacked a way to propagate `format` options during standard `SendMessage` execution. Clients were forced to use multi-step workaround sequences (`SendMessage` -> `opencode.sessions.prompt_async`).

## Changes Made

### 1. `send_message` Client Parameter
- Added `format_override: Mapping[str, Any] | None` parameter to `OpencodeUpstreamClient.send_message()`.
- Passes `payload["format"] = format_override` directly to OpenCode's `POST /session/{id}/message` endpoint.

### 2. A2A Request Metadata Extraction
- In `OpencodeAgentExecutor`, extracted `metadata.shared.format` from incoming `RequestContext` metadata.
- Validates that `format` specifies `{type: "json_schema", schema: object}`.

### 3. Session Poisoning Prevention (H-03 Guardrail)
- Client-side stripping of `retryCount` from the format payload before forwarding to OpenCode.
- **Reason**: The OpenCode v2 upstream server rejects `retryCount` inside schema format objects during session reads, permanently corrupting the session state (`400 Bad Request` on subsequent GETs). Stripping it client-side protects all downstream sessions.

### 4. Structured Output Artifact Extraction
- When OpenCode returns a model tool call named `StructuredOutput` containing validated JSON in `state.input`, `ExecutionCoordinator._handle_non_streaming_response` extracts and surfaces this JSON directly as an A2A `Artifact` named `structured_output` (with a `data` part).

## Benefits & Improvements
1. **Single Round-Trip**: A2A clients can request structured JSON responses in a single unary `SendMessage` call without needing asynchronous session polling.
2. **Reliable Tool Output Parsing**: Removes fragile free-text regex parsing by leveraging OpenCode's native JSON Schema validation.
3. **Session Safety**: Protects OpenCode session state against permanent corruption caused by `retryCount` field mismatches.
4. **Full Backward Compatibility**: Unspecified `format` payloads continue with default behavior without overhead or breaking changes.
