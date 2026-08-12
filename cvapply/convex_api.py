from __future__ import annotations

import time
from typing import Any

import requests
from requests import Response

from .config import settings


class ConvexClient:
    def __init__(self) -> None:
        self.url = settings.convex_deploy_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        # NOTE: this dev deployment allows anonymous queries/mutations (default
        # for dev deployments). The `dev:` deploy key is a CLI admin key, not a
        # JWT, so it is not accepted by the REST API. If the deployment is ever
        # locked down, generate a client JWT and set it as a Bearer header here.

    def _call(self, kind: str, path: str, args: dict[str, Any] | None = None) -> Any:
        payload = {"path": path, "args": args or {}}
        last_exc: Exception | None = None
        for attempt in range(4):
            try:
                resp: Response = self.session.post(
                    f"{self.url}/api/{kind}", json=payload, timeout=120
                )
                if resp.status_code == 429:
                    time.sleep(5 * (attempt + 1))
                    continue
                if resp.status_code >= 500:
                    raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
                if data.get("status") == "error":
                    raise RuntimeError(
                        f"Convex {kind} '{path}' error: {data.get('code')} {data.get('message')}"
                    )
                return data.get("value")
            except (requests.RequestException, RuntimeError) as exc:
                last_exc = exc
                time.sleep(min(2 ** attempt, 10))
        raise RuntimeError(f"Convex {kind} '{path}' failed after retries: {last_exc}")

    def query(self, path: str, args: dict[str, Any] | None = None) -> Any:
        return self._call("query", path, args)

    def mutation(self, path: str, args: dict[str, Any] | None = None) -> Any:
        return self._call("mutation", path, args)