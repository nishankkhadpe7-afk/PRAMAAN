"""S4: reject oversized request bodies before they are buffered and parsed.

Uploads travel as base64 inside JSON, so the transport limit is the decoded-upload limit
expanded by base64 (4/3) plus room for the surrounding JSON. Both a declared Content-Length
and the bytes actually streamed are enforced, so chunked bodies cannot bypass the limit.
"""
from __future__ import annotations

import json

from fastapi import HTTPException

from .upload_safety import max_upload_bytes

JSON_OVERHEAD = 1024 * 1024


def max_body_bytes() -> int:
    return (max_upload_bytes() * 4) // 3 + JSON_OVERHEAD


class BodySizeLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = max_body_bytes()
        declared = dict(scope.get("headers", [])).get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    return await _reject(send)
            except ValueError:
                return await _reject(send, 400, "bad_request", "invalid Content-Length")
        received = 0
        rejected = False

        async def limited_receive():
            nonlocal received, rejected
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    rejected = True
                    raise BodyTooLarge()
            return message

        response_started = False

        async def tracking_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)
        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLarge:
            if not response_started:
                await _reject(send)


class BodyTooLarge(HTTPException):
    """Raised mid-stream; FastAPI re-raises HTTPException from body parsing, so the client gets 413."""

    def __init__(self):
        super().__init__(413, "request body exceeds the configured upload limit")


async def _reject(send, status=413, code="payload_too_large", detail="request body exceeds the configured upload limit"):
    body = json.dumps({"code": code, "detail": detail}).encode()
    await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
