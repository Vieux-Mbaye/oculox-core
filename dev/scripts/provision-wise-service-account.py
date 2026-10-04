#!/usr/bin/env python3

"""Provision the Arkime service identity used by the protected WISE route."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse


PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CURLRC = PROJECT_DIR / "dev/generated/opensearch-clients/arkime.curlrc"
DEFAULT_ARKIME_ENV = PROJECT_DIR / "config/arkime-secret.env"
DEFAULT_AUTH_ENV = PROJECT_DIR / "config/auth.env"
DEFAULT_HTPASSWD = PROJECT_DIR / "nginx/htpasswd"
LOCAL_WISE_URLS = {"http://arkime:8081", "http://arkime:8081/"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
USER_LINE_RE = re.compile(
    r"^\s*user\s*[:=]\s*(?:\"([^\"]+)\"|'([^']+)'|(\S+))\s*$",
    re.MULTILINE,
)


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def read_curl_identity(path: Path) -> tuple[str, str]:
    if not path.is_file():
        raise RuntimeError(f"Arkime credential file is missing: {path}")
    match = USER_LINE_RE.search(path.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError(f"Arkime credential file has no curl user entry: {path}")
    value = next(group for group in match.groups() if group is not None)
    if ":" not in value:
        raise RuntimeError("Arkime curl user entry does not contain a password")
    username, password = value.split(":", 1)
    if not USERNAME_RE.fullmatch(username) or not password or "\n" in password:
        raise RuntimeError("Arkime curl user entry is invalid")
    return username, password


def wise_requires_service_account(path: Path) -> bool:
    url = read_env(path).get("ARKIME_WISE_SERVICE_URL", "").strip()
    if not url or url.lower() == "disabled" or url in LOCAL_WISE_URLS:
        return False
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise RuntimeError(
            "Remote Arkime WISE URL must be HTTPS and must not embed credentials"
        )
    return True


def bcrypt_entry(username: str, password: str) -> str:
    binary = shutil.which("htpasswd")
    if not binary:
        raise RuntimeError("htpasswd is required to provision the WISE service account")
    process = subprocess.run(
        [binary, "-i", "-n", "-B", username],
        input=password + "\n",
        capture_output=True,
        text=True,
        check=False,
    )
    line = process.stdout.strip()
    if process.returncode or not line.startswith(f"{username}:"):
        raise RuntimeError("Unable to hash the WISE service account password")
    return line


def install_entry(path: Path, username: str, entry: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    retained = [line for line in existing if not line.startswith(f"{username}:")]
    content = "\n".join([*retained, entry]) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=".htpasswd.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def verify_entry(path: Path, username: str, password: str) -> None:
    binary = shutil.which("htpasswd")
    if not binary or not path.is_file():
        raise RuntimeError("WISE service account password file is unavailable")
    process = subprocess.run(
        [binary, "-i", "-v", str(path), username],
        input=password + "\n",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if process.returncode:
        raise RuntimeError("WISE service account verification failed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--curlrc", type=Path, default=DEFAULT_CURLRC)
    parser.add_argument("--arkime-env", type=Path, default=DEFAULT_ARKIME_ENV)
    parser.add_argument("--auth-env", type=Path, default=DEFAULT_AUTH_ENV)
    parser.add_argument("--htpasswd", type=Path, default=DEFAULT_HTPASSWD)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if not wise_requires_service_account(args.arkime_env):
        print("WISE_SERVICE_ACCOUNT=SKIP: local or disabled WISE endpoint")
        return

    username, password = read_curl_identity(args.curlrc)
    administrator = read_env(args.auth_env).get("MALCOLM_USERNAME", "")
    if administrator == username:
        raise SystemExit(
            f"The administrator username {username!r} is reserved for the Arkime service"
        )

    if not args.check:
        install_entry(args.htpasswd, username, bcrypt_entry(username, password))
    verify_entry(args.htpasswd, username, password)
    print(f"WISE_SERVICE_ACCOUNT=PASS user={username}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        raise SystemExit(f"WISE service account error: {error}") from error
