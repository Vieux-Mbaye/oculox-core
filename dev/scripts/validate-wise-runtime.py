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


def container_for(service: str) -> str:
    project = PROJECT_DIR.name.lower()
    result = run(
        "docker",
        "ps",
        "--filter",
        f"label=com.docker.compose.project={project}",
        "--filter",
        f"label=com.docker.compose.service={service}",
        "--format",
        "{{.ID}}",
    )
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""


def validate_once() -> tuple[bool, str]:
    arkime = read_env(PROJECT_DIR / "config/arkime-secret.env")
    live = read_env(PROJECT_DIR / "config/arkime-live.env")
    wise_url = arkime.get("ARKIME_WISE_SERVICE_URL", "").rstrip("/")
    if not wise_url or wise_url.lower() == "disabled":
        return True, "WISE_RUNTIME=SKIP: WISE endpoint is disabled"

    arkime_container = container_for("arkime")
    if not arkime_container:
        return False, "Arkime container is not running"

    if wise_url == "http://arkime:8081":
        response = run(
            "docker",
            "exec",
            arkime_container,
            "curl",
            "--silent",
            "--show-error",
            "--max-time",
            "10",
            "--output",
            "/dev/null",
            "--write-out",
            "%{http_code}",
            "http://127.0.0.1:8081/fields?ver=1",
        )
    else:
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

    wise_config = run(
        "docker", "exec", arkime_container, "cat", "/opt/arkime/wiseini/wise.ini"
    )
    required_config = (
        "[user-auto-create]",
        "userName=vals['x-forwarded-user']",
        "headerAuthEnabled=true",
        "[user-role-mappings]",
        "wiseUser=",
        "wiseAdmin=",
    )
    if wise_config.returncode or any(
        setting not in wise_config.stdout for setting in required_config
    ):
        return False, "WISE Keycloak user auto-provisioning configuration is incomplete"

    if live.get("ARKIME_LIVE_CAPTURE", "false").lower() == "true":
        container = container_for("arkime-live")
        if not container:
            return False, "Arkime Live container is not running"
        processes = run("docker", "top", container, "-eo", "pid,args")
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
