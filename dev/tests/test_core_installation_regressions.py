#!/usr/bin/env python3

"""Regression tests for Core installation integration points."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_wise_module():
    path = ROOT / "dev/scripts/provision-wise-service-account.py"
    spec = importlib.util.spec_from_file_location("provision_wise_service_account", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def load_deployment_role_module():
    path = ROOT / "dev/scripts/configure-deployment-role.py"
    spec = importlib.util.spec_from_file_location("configure_deployment_role", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def load_arkime_identity_module():
    path = ROOT / "dev/scripts/configure-arkime-identity.py"
    spec = importlib.util.spec_from_file_location("configure_arkime_identity", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


WISE = load_wise_module()
DEPLOYMENT_ROLE = load_deployment_role_module()
ARKIME_IDENTITY = load_arkime_identity_module()


class ArkimeIdentityTests(unittest.TestCase):
    def test_wise_identity_sections_are_idempotent_and_preserve_sources(self):
        source = """[wiseService]
authMode=header
userNameHeader=x-forwarded-user

[virustotal]
key=keep-this-secret
"""
        sections = ARKIME_IDENTITY.managed_sections(
            {
                "ROLE_ARKIME_WISE_READ_ACCESS": "custom_wise_read",
                "ROLE_ARKIME_WISE_READ_WRITE_ACCESS": "custom_wise_admin",
            }
        )
        updated = source
        for section, values in sections.items():
            updated = ARKIME_IDENTITY.upsert_section(updated, section, values)
        once = updated
        for section, values in sections.items():
            updated = ARKIME_IDENTITY.upsert_section(updated, section, values)

        self.assertEqual(once, updated)
        self.assertIn("key=keep-this-secret", updated)
        self.assertIn("userName=vals['x-forwarded-user']", updated)
        self.assertIn("includes('custom_wise_read')", updated)
        self.assertIn("includes('custom_wise_admin')", updated)
        self.assertEqual(1, updated.count("[user-auto-create]"))
        self.assertEqual(1, updated.count("[user-role-mappings]"))

    def test_invalid_role_value_is_rejected(self):
        with self.assertRaises(ValueError):
            ARKIME_IDENTITY.role_expression("role'); process.exit()")

    def test_runtime_file_is_private_when_created(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / "wise.ini.example"
            runtime = root / "wise.ini"
            template.write_text("[wiseService]\nauthMode=header\n", encoding="utf-8")
            shutil.copyfile(template, runtime)
            os.chmod(runtime, 0o600)
            ARKIME_IDENTITY.update_file(
                runtime, ARKIME_IDENTITY.managed_sections({})
            )
            self.assertEqual(0o600, runtime.stat().st_mode & 0o777)

    def test_runtime_reconciliation_does_not_modify_tracked_template(self):
        source = (ROOT / "dev/scripts/configure-arkime-identity.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("update_file(args.template", source)
        self.assertIn("update_file(args.runtime", source)

    def test_production_compose_mounts_reviewed_arkime_configuration(self):
        compose = (ROOT / "dev/compose/docker-compose.dev.yml").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            2,
            compose.count(
                "./arkime/scripts/docker_entrypoint.sh:/usr/local/bin/docker_entrypoint.sh:ro"
            ),
        )
        self.assertEqual(
            2,
            compose.count("./arkime/scripts/initarkime.sh:/usr/local/bin/initarkime.sh:ro"),
        )

    def test_arkime_refresh_is_limited_to_arkime_indices(self):
        source = (ROOT / "arkime/scripts/initarkime.sh").read_text(encoding="utf-8")
        self.assertIn('${OPENSEARCH_URL}/arkime_*/_refresh', source)
        self.assertNotIn('${OPENSEARCH_URL}/_refresh', source)

    def test_launcher_reconciles_identity_before_compose_render(self):
        source = (ROOT / "oculox").read_text(encoding="utf-8")
        start = source.index("official_start() {")
        identity = source.index("./dev/scripts/configure-arkime-identity.py", start)
        render = source.index("render_runtime_compose", identity)
        self.assertLess(identity, render)


class ArkimeViewerRoutingTests(unittest.TestCase):
    def test_principal_advertises_public_server_name_for_live_viewer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            config.mkdir()
            env = config / "arkime-live.env"
            env.write_text("ARKIME_LIVE_NODE_HOST=\nWISE=on\n", encoding="utf-8")

            DEPLOYMENT_ROLE.configure_live_viewer_host(
                root, "principal", "core.example.test"
            )

            self.assertIn(
                "ARKIME_LIVE_NODE_HOST=core.example.test\n",
                env.read_text(encoding="utf-8"),
            )
            self.assertEqual(0o600, os.stat(env).st_mode & 0o777)

    def test_hedgehog_does_not_override_live_viewer_host(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            config.mkdir()
            env = config / "arkime-live.env"
            original = "ARKIME_LIVE_NODE_HOST=collector.example.test\n"
            env.write_text(original, encoding="utf-8")

            DEPLOYMENT_ROLE.configure_live_viewer_host(root, "hedgehog", None)

            self.assertEqual(original, env.read_text(encoding="utf-8"))


@unittest.skipUnless(shutil.which("htpasswd"), "htpasswd is required")
class WiseServiceAccountTests(unittest.TestCase):
    def test_remote_wise_account_is_idempotent_and_preserves_admin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            curlrc = root / "arkime.curlrc"
            arkime_env = root / "arkime.env"
            auth_env = root / "auth.env"
            htpasswd = root / "htpasswd"
            curlrc.write_text('user: "oculox_arkime:a-long-test-password"\n', encoding="utf-8")
            arkime_env.write_text(
                "ARKIME_WISE_SERVICE_URL=https://core.example.test/wise/\n", encoding="utf-8"
            )
            auth_env.write_text("MALCOLM_USERNAME=admin\n", encoding="utf-8")
            admin = subprocess.run(
                [shutil.which("htpasswd"), "-i", "-n", "-B", "admin"],
                input="admin-test-password\n",
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            htpasswd.write_text(admin + "\n", encoding="utf-8")

            username, password = WISE.read_curl_identity(curlrc)
            for _ in range(2):
                WISE.install_entry(htpasswd, username, WISE.bcrypt_entry(username, password))
                WISE.verify_entry(htpasswd, username, password)

            lines = htpasswd.read_text(encoding="utf-8").splitlines()
            self.assertEqual(1, sum(line.startswith("admin:") for line in lines))
            self.assertEqual(1, sum(line.startswith("oculox_arkime:") for line in lines))
            self.assertEqual(0o600, os.stat(htpasswd).st_mode & 0o777)

    def test_remote_url_must_not_contain_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "arkime.env"
            env.write_text(
                "ARKIME_WISE_SERVICE_URL=https://user:password@core.example.test/wise/\n",
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                WISE.wise_requires_service_account(env)

    def test_local_or_disabled_wise_needs_no_service_account(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "arkime.env"
            for value in ("", "disabled", "http://arkime:8081", "http://arkime:8081/"):
                with self.subTest(value=value):
                    env.write_text(f"ARKIME_WISE_SERVICE_URL={value}\n", encoding="utf-8")
                    self.assertFalse(WISE.wise_requires_service_account(env))


class DashboardsLinkTests(unittest.TestCase):
    def test_installer_provides_repository_audit_dependency(self):
        source = (ROOT / "scripts/installer/platforms/linux.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count("'ripgrep'"), 2)

    def test_client_validator_does_not_hardcode_compose_project_name(self):
        source = (
            ROOT / "dev/tests/opensearch-cluster/validate-client-connectivity.py"
        ).read_text(encoding="utf-8")
        self.assertIn("com.docker.compose.project.config_files={RUNTIME_COMPOSE}", source)
        self.assertNotIn("com.docker.compose.project=oculox\"", source)

    def test_remote_opensearch_links_are_absolute_and_repairable(self):
        source = (ROOT / "dashboards/scripts/index-refresh.py").read_text(encoding="utf-8")
        self.assertIn("int(DatabaseMode.OpenSearchRemote)", source)
        self.assertIn("'iddash2ark' not in str(existing_url)", source)
        self.assertIn("elif args.malcolm_url or (not elasticsearch_remote):", source)

    def test_installation_provisions_wise_after_authentication(self):
        source = (ROOT / "oculox").read_text(encoding="utf-8")
        auth_position = source.index("    ./scripts/auth_setup\n")
        wise_position = source.index('    provision_wise_service_account "$ROLE"\n')
        self.assertGreater(wise_position, auth_position)
        self.assertIn('./dev/scripts/validate-wise-runtime.py --wait 300', source)

        validator = (ROOT / "dev/scripts/validate-wise-runtime.py").read_text(encoding="utf-8")
        self.assertIn('"docker", "top", container, "-eo", "pid,args"', validator)
        self.assertIn("WISE Keycloak user auto-provisioning configuration is incomplete", validator)
        self.assertIn('"[user-auto-create]"', validator)
        self.assertIn('"[user-role-mappings]"', validator)

    def test_public_endpoint_configures_absolute_dashboards_links(self):
        source = (ROOT / "dev/scripts/configure-public-endpoint.py").read_text(encoding="utf-8")
        self.assertIn('default=PROJECT_DIR / "config/dashboards-helper.env"', source)
        self.assertIn('"MALCOLM_URL": public_url', source)


if __name__ == "__main__":
    unittest.main()
