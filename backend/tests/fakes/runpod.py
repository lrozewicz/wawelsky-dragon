"""Fałszywe API RunPod v2 (``httpx.MockTransport``) — stan w pamięci, bez sieci i kosztów."""

from __future__ import annotations

import json
from typing import Any

import httpx

GPU_ROWS: list[dict[str, Any]] = [
    {
        "id": "NVIDIA GeForce RTX 4090",
        "name": "RTX 4090",
        "memory": 24,
        "manufacturer": "NVIDIA",
        "secure": True,
        "community": True,
        "price": {"secure": 0.89, "community": 0.69},
        "availability": "HIGH",
        "dataCenters": [
            {"id": "EU-RO-1", "name": "Romania", "availability": "HIGH"},
            {"id": "US-TX-3", "name": "Texas", "availability": "LOW"},
        ],
    },
    {
        "id": "NVIDIA RTX A4000",
        "name": "RTX A4000",
        "memory": 16,
        "manufacturer": "NVIDIA",
        "secure": True,
        "community": False,
        "price": {"secure": 0.25, "community": 0},
        "availability": "NONE",
        "dataCenters": [],
    },
    {
        "id": "NVIDIA A40",
        "name": "A40",
        "memory": 48,
        "manufacturer": "NVIDIA",
        "secure": True,
        "community": False,
        "price": {"secure": 0.59, "community": 0},
        "availability": "MEDIUM",
        "dataCenters": [{"id": "EU-CZ-1", "name": "Czechia", "availability": "MEDIUM"}],
    },
    {
        "id": "NVIDIA L4",
        "name": "L4",
        "memory": 24,
        "manufacturer": "NVIDIA",
        "secure": True,
        "community": False,
        "price": {"secure": 0.39, "community": 0},
        "availability": "LOW",
        "dataCenters": [{"id": "EU-RO-1", "name": "Romania", "availability": "LOW"}],
    },
    {
        "id": "NVIDIA GeForce RTX 3060",
        "name": "RTX 3060",
        "memory": 12,
        "manufacturer": "NVIDIA",
        "secure": True,
        "community": False,
        "price": {"secure": 0.2, "community": 0},
        "availability": "HIGH",
        "dataCenters": [{"id": "EU-RO-1", "name": "Romania", "availability": "HIGH"}],
    },
    {
        "id": "AMD Instinct MI300X OAM",
        "name": "MI300X",
        "memory": 192,
        "manufacturer": "AMD",
        "secure": True,
        "community": False,
        "price": {"secure": 2.39, "community": 0},
        "availability": "HIGH",
        "dataCenters": [],
    },
]

DATA_CENTERS = [
    {"id": "EU-RO-1", "name": "Romania", "region": "EUROPE"},
    {"id": "EU-CZ-1", "name": "Czechia", "region": "EUROPE"},
    {"id": "US-TX-3", "name": "Texas", "region": "NORTH_AMERICA"},
]


class FakeRunpod:
    """Stan i obsługa żądań; ``client()`` zwraca ``httpx.AsyncClient`` na tej atrapie."""

    def __init__(self, valid_key: str = "rpa_test") -> None:
        self.valid_key = valid_key
        self.pods: dict[str, dict[str, Any]] = {}
        self.requests: list[tuple[str, str]] = []
        self.create_error: tuple[int, str] | None = None
        self.delete_error: tuple[int, str] | None = None
        self.next_status = "PROVISIONING"

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    def set_status(self, pod_id: str, status: str) -> None:
        self.pods[pod_id]["status"] = status

    def handle(self, request: httpx.Request) -> httpx.Response:  # noqa: PLR0911
        path = request.url.path.removeprefix("/v2")
        self.requests.append((request.method, path))
        if request.headers.get("authorization") != f"Bearer {self.valid_key}":
            return httpx.Response(401, json={"title": "Unauthorized"})
        if request.method == "GET" and path == "/catalog/gpus":
            return httpx.Response(200, json={"gpus": GPU_ROWS})
        if request.method == "GET" and path == "/catalog/datacenters":
            return httpx.Response(200, json={"dataCenters": DATA_CENTERS})
        if request.method == "GET" and path == "/pods":
            return httpx.Response(200, json={"pods": list(self.pods.values())})
        if request.method == "POST" and path == "/pods":
            return self._create(json.loads(request.content))
        pod_id = path.removeprefix("/pods/")
        if path.startswith("/pods/") and pod_id not in self.pods:
            return httpx.Response(404, json={"title": "Not Found"})
        if request.method == "GET":
            return httpx.Response(200, json=self.pods[pod_id])
        if request.method == "DELETE":
            if self.delete_error is not None:
                status, detail = self.delete_error
                return httpx.Response(status, json={"detail": detail})
            self.pods[pod_id]["status"] = "TERMINATED"
            return httpx.Response(204)
        return httpx.Response(405)

    def _create(self, body: dict[str, Any]) -> httpx.Response:
        if self.create_error is not None:
            status, detail = self.create_error
            return httpx.Response(status, json={"detail": detail})
        pod_id = f"pod{len(self.pods) + 1:04d}"
        self.pods[pod_id] = {
            "id": pod_id,
            "status": self.next_status,
            "cost": 0.89,
            "dataCenterId": "EU-RO-1",
            "body": body,
        }
        return httpx.Response(201, json=self.pods[pod_id])
