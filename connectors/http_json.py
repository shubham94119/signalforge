"""Generic read-only HTTP JSON connector.

This adapter is intentionally vendor-neutral. A source endpoint must expose
these query operations on the configured URL:

``poll`` (default): ``items``/``changes`` and optional ``next_cursor``;
``fetch``: one source object; ``health``: connector health metadata.

Each upsert item uses the canonical JSON shape accepted by
``source_record_from_mapping``. Vendor-specific connectors can wrap this
adapter once their ACL and pagination semantics are known.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping, Optional

from incident_intelligence.ingestion import SourceRecord
from incident_intelligence.models import ACL

from .base import ConnectorBatch, ConnectorHealth, SourceChange
from .jsonl import source_record_from_mapping


class HttpJsonConnector:
    def __init__(
        self,
        base_url: str,
        source_instance: str,
        *,
        auth_token: str | None = None,
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must be an http(s) URL")
        self.base_url = base_url
        self.source_instance = source_instance
        self.auth_token = auth_token
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)

    def _request_json(self, operation: str, **params: Any) -> Mapping[str, Any] | list[Any]:
        query = {"operation": operation, **{key: value for key, value in params.items() if value is not None}}
        url = f"{self.base_url}?{urllib.parse.urlencode(query)}"
        headers = {"Accept": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        request = urllib.request.Request(url, headers=headers, method="GET")
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, (dict, list)):
                    raise ValueError("connector response must be a JSON object or list")
                return payload
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(min(2**attempt, 4))
        raise RuntimeError(f"connector {self.source_instance} {operation} request failed") from last_error

    def _items(self, payload: Mapping[str, Any] | list[Any]) -> tuple[list[dict[str, Any]], Optional[str], bool]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)], None, False
        raw_items = payload.get("changes", payload.get("items", []))
        if not isinstance(raw_items, list):
            raise ValueError("connector response items/changes must be a list")
        next_cursor = payload.get("next_cursor")
        return [item for item in raw_items if isinstance(item, dict)], str(next_cursor) if next_cursor is not None else None, bool(payload.get("has_more", next_cursor is not None))

    def discover(self) -> tuple[tuple[dict[str, Any], ...], Optional[str]]:
        payload = self._request_json("poll", cursor=None, limit=100)
        items, next_cursor, _ = self._items(payload)
        return tuple(items), next_cursor

    def fetch(self, source_object_id: str, source_version: str) -> dict[str, Any]:
        payload = self._request_json("fetch", source_object_id=source_object_id, source_version=source_version)
        if not isinstance(payload, dict):
            raise ValueError("fetch response must be a JSON object")
        return dict(payload.get("record", payload))

    def fetch_acl(self, source_object_id: str, source_version: str) -> ACL:
        return self.normalize(self.fetch(source_object_id, source_version)).acl

    def normalize(self, source_object: dict[str, Any]) -> SourceRecord:
        record = source_record_from_mapping(source_object)
        if record.source_instance != self.source_instance:
            raise ValueError("source record instance does not match connector")
        return record

    def poll(self, cursor: Optional[str], limit: int = 100) -> ConnectorBatch:
        payload = self._request_json("poll", cursor=cursor, limit=limit)
        items, next_cursor, has_more = self._items(payload)
        changes: list[SourceChange] = []
        for item in items:
            kind = item.get("kind", "upsert")
            if kind == "delete":
                changes.append(
                    SourceChange(
                        kind="delete",
                        source_object_id=str(item["source_object_id"]),
                        source_version=str(item["source_version"]),
                    )
                )
                continue
            record = self.normalize(dict(item.get("record", item)))
            changes.append(
                SourceChange(
                    kind="upsert",
                    source_object_id=record.source_object_id,
                    source_version=record.source_version,
                    record=record,
                )
            )
        return ConnectorBatch(tuple(changes), next_cursor, has_more)

    def health(self) -> ConnectorHealth:
        try:
            payload = self._request_json("health")
            if isinstance(payload, dict):
                return ConnectorHealth(
                    self.source_instance,
                    str(payload.get("status", "ok")),
                    int(payload["cursor_lag"]) if payload.get("cursor_lag") is not None else None,
                    str(payload.get("message")) if payload.get("message") else None,
                )
            return ConnectorHealth(self.source_instance, "ok")
        except Exception as exc:  # noqa: BLE001 - health must report, not crash a dashboard
            return ConnectorHealth(self.source_instance, "error", message=str(exc))
