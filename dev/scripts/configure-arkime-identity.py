#!/usr/bin/env python3

"""Keep Arkime and WISE header-auth user provisioning aligned with Oculox RBAC."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
ROLE_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")

AUTO_CREATE = {
    "userName": "vals['x-forwarded-user']",
    "enabled": "true",
    "webEnabled": "true",
    "headerAuthEnabled": "true",
    "emailSearch": "true",
    "createEnabled": "false",
    "removeEnabled": "false",
    "packetSearch": "true",
    "hideStats": "false",
    "hideFiles": "false",
    "hidePcap": "false",
    "disablePcapDownload": "false",
    "roles": "['arkimeUser']",
}


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


def role_expression(header_role: str) -> str:
    if not ROLE_RE.fullmatch(header_role):
        raise ValueError(f"Invalid Arkime role value: {header_role!r}")
    return (
        "(vals['x-forwarded-roles'] || '').split(',')"
        f".map(s => s.trim()).includes('{header_role}')"
    )


def managed_sections(roles: dict[str, str]) -> dict[str, dict[str, str]]:
    read_role = roles.get("ROLE_ARKIME_WISE_READ_ACCESS", "arkime_wise_read_access")
    admin_role = roles.get(
        "ROLE_ARKIME_WISE_READ_WRITE_ACCESS", "arkime_wise_read_write_access"
    )
    return {
        "user-auto-create": AUTO_CREATE,
        "user-role-mappings": {
            "arkimeUser": "true",
            "wiseUser": role_expression(read_role),
            "wiseAdmin": role_expression(admin_role),
        },
    }


def upsert_section(text: str, section: str, values: dict[str, str]) -> str:
    lines = text.splitlines()
    header = f"[{section}]"
    start = next((index for index, line in enumerate(lines) if line.strip() == header), None)
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([header, *(f"{key}={value}" for key, value in values.items())])
        return "\n".join(lines) + "\n"

    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].strip().startswith("[") and lines[index].strip().endswith("]")
        ),
        len(lines),
    )
    managed_keys = set(values)
    retained = []
    for line in lines[start + 1 : end]:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key not in managed_keys:
            retained.append(line)
    while retained and not retained[-1].strip():
        retained.pop()
    replacement = [header, *retained, *(f"{key}={value}" for key, value in values.items()), ""]
    updated = lines[:start] + replacement + lines[end:]
    return "\n".join(updated).rstrip() + "\n"


def update_file(path: Path, sections: dict[str, dict[str, str]]) -> None:
    original = path.read_text(encoding="utf-8")
    updated = original
    for section, values in sections.items():
        updated = upsert_section(updated, section, values)
    if updated == original:
        return

    mode = path.stat().st_mode & 0o777
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(updated)
        temporary = Path(handle.name)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--template", type=Path, default=PROJECT_DIR / "arkime/etc/wise.ini.example"
    )
    parser.add_argument(
        "--runtime", type=Path, default=PROJECT_DIR / "arkime/etc/wise.ini"
    )
    parser.add_argument(
        "--roles-env", type=Path, default=PROJECT_DIR / "config/auth-common.env"
    )
    args = parser.parse_args()

    if not args.template.is_file():
        raise SystemExit(f"WISE template not found: {args.template}")
    if not args.runtime.exists():
        args.runtime.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.template, args.runtime)
        os.chmod(args.runtime, 0o600)

    sections = managed_sections(read_env(args.roles_env))
    update_file(args.runtime, sections)
    print("ARKIME_IDENTITY_CONFIG_RESULT=PASS")


if __name__ == "__main__":
    main()
