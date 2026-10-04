#!/usr/bin/env python3

"""Validate authenticated WISE access and the Arkime live capture process."""

from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def run(*command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def validate_once() -> tuple[bool, str]:
    arkime = read_env(PROJECT_DIR / "config/arkime-secret.env")
    live = read_env(PROJECT_DIR / "config/arkime-live.env")
    wise_url = arkime.get("ARKIME_WISE_SERVICE_URL", "").rstrip("/")
    if not wise_url or wise_url.lower() == "disabled" or wise_url == "http://arkime:8081":
        return True, "WISE_RUNTIME=SKIP: local or disabled WISE endpoint"

    curlrc = PROJECT_DIR / "dev/generated/opensearch-clients/arkime.curlrc"
    ca = PROJECT_DIR / "nginx/ca-trust/oculox-web-ca.crt"
    if not curlrc.is_file() or not ca.is_file():
        return False, "WISE runtime credentials or web CA are missing"
    response = run(
        "curl",
        "--config",
        str(curlrc),
        "--cacert",
        str(ca),
        "--silent",
        "--show-error",
        "--max-time",
        "10",
        "--output",
        "/dev/null",
        "--write-out",
        "%{http_code}",
        f"{wise_url}/fields?ver=1",
    )
    if response.returncode or response.stdout != "200":
        return False, f"WISE endpoint failed with HTTP {response.stdout or 'connection-error'}"

    if live.get("ARKIME_LIVE_CAPTURE", "false").lower() == "true":
        project = PROJECT_DIR.name.lower()
        container = run(
            "docker",
            "ps",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--filter",
            "label=com.docker.compose.service=arkime-live",
            "--format",
            "{{.ID}}",
        ).stdout.strip()
        if not container:
            return False, "Arkime Live container is not running"
        processes = run("docker", "top", container.splitlines()[0], "-eo", "pid,args")
        if processes.returncode or "/opt/arkime/bin/capture" not in processes.stdout:
            return False, "Arkime Live capture process is not running"

    return True, "WISE_RUNTIME=PASS authenticated endpoint and Arkime capture"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait", type=int, default=0, help="seconds to wait for startup")
    args = parser.parse_args()
    deadline = time.monotonic() + max(args.wait, 0)
    while True:
        success, message = validate_once()
        if success:
            print(message)
            return
        if time.monotonic() >= deadline:
            raise SystemExit(f"WISE_RUNTIME=FAIL: {message}")
        time.sleep(5)


if __name__ == "__main__":
    main()
