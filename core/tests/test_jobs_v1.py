from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from faceforge_core.app import create_app


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _wait_for_job(
    client: TestClient, *, headers: dict[str, str], job_id: str, timeout_s: float = 10.0
):
    start = time.time()
    while True:
        r = client.get(f"/v1/jobs/{job_id}", headers=headers)
        assert r.status_code == 200
        job = r.json()["data"]
        if job["status"] in {"succeeded", "failed", "canceled"}:
            return job
        if time.time() - start > timeout_s:
            raise AssertionError(f"Timed out waiting for job {job_id} (status={job['status']})")
        time.sleep(0.05)


def test_jobs_create_get_log_and_bulk_import(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FACEFORGE_HOME", str(tmp_path))

    src = tmp_path / "import"
    src.mkdir(parents=True, exist_ok=True)

    content = b"hello bulk"
    f1 = src / "hello.txt"
    f1.write_bytes(content)
    (src / "hello_meta.json").write_text('{"note": "sidecar"}', encoding="utf-8")

    with TestClient(create_app()) as client:
        app = cast(FastAPI, client.app)
        token = app.state.faceforge_config.auth.install_token
        headers = {"Authorization": f"Bearer {token}"}

        # Start job via the bulk-import convenience endpoint.
        r = client.post(
            "/v1/assets/bulk-import",
            headers=headers,
            json={"path": str(src), "recursive": True, "kind": "file"},
        )
        assert r.status_code == 200
        job_id = r.json()["data"]["job_id"]

        job = _wait_for_job(client, headers=headers, job_id=job_id)
        assert job["status"] == "succeeded"

        listing = client.get("/v1/jobs", headers=headers)
        assert listing.status_code == 200
        body = listing.json()["data"]
        assert body["total"] >= 1
        assert any(x["job_id"] == job_id for x in body["items"])

        # Logs are append-only and pollable.
        log1 = client.get(f"/v1/jobs/{job_id}/log", headers=headers)
        assert log1.status_code == 200
        data1 = log1.json()["data"]
        assert isinstance(data1["items"], list)
        assert data1["next_after_id"] >= 0

        # Import created an asset that can be fetched and downloaded.
        asset_id = _sha256_hex(content)
        meta = client.get(f"/v1/assets/{asset_id}", headers=headers)
        assert meta.status_code == 200
        meta_obj = meta.json()["data"]["meta"]
        assert any(x.get("Source") == "UserSidecar" for x in meta_obj.get("metadata", []))

        dl = client.get(f"/v1/assets/{asset_id}/download", headers=headers)
        assert dl.status_code == 200
        assert dl.content == content


def test_jobs_cancel_is_cooperative_and_predictable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FACEFORGE_HOME", str(tmp_path))

    src = tmp_path / "import"
    src.mkdir(parents=True, exist_ok=True)

    # Make enough files that the job is still running when we cancel.
    for i in range(20):
        (src / f"f{i:02d}.bin").write_bytes(b"x" * 1024)

    with TestClient(create_app()) as client:
        app = cast(FastAPI, client.app)
        token = app.state.faceforge_config.auth.install_token
        headers = {"Authorization": f"Bearer {token}"}

        r = client.post(
            "/v1/jobs",
            headers=headers,
            json={
                "job_type": "assets.bulk-import",
                "input": {"path": str(src), "recursive": True, "kind": "file", "throttle_ms": 25},
            },
        )
        assert r.status_code == 200
        job_id = r.json()["data"]["job_id"]

        cancel = client.post(f"/v1/jobs/{job_id}/cancel", headers=headers)
        assert cancel.status_code == 200
        assert cancel.json()["data"]["cancel_requested"] is True

        job = _wait_for_job(client, headers=headers, job_id=job_id, timeout_s=10.0)
        assert job["status"] == "canceled"

        logs = client.get(f"/v1/jobs/{job_id}/log", headers=headers)
        assert logs.status_code == 200
        assert any(x.get("message") == "Cancel requested" for x in logs.json()["data"]["items"])
