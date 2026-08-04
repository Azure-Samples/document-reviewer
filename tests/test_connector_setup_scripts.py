from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "infra" / "scripts"


def _read(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def test_azd_postdeploy_registers_trigger_and_generates_samples() -> None:
    azure_yaml = (ROOT / "azure.yaml").read_text(encoding="utf-8")

    assert (
        "run: ./infra/scripts/configure-trigger.sh && "
        "uv run --script scripts/create_sample_documents.py"
    ) in azure_yaml
    assert (
        "run: ./infra/scripts/configure-trigger.ps1 && "
        "uv run --script scripts/create_sample_documents.py"
    ) in azure_yaml
    assert azure_yaml.count("interactive: false") == 2
    assert "interactive: true" not in azure_yaml
    assert "configure_connectors.py" not in azure_yaml


@pytest.mark.parametrize("extension", ["sh", "ps1"])
def test_trigger_scripts_register_the_fixed_sharepoint_source(extension: str) -> None:
    script = _read(f"configure-trigger.{extension}")

    for expected in (
        "document_review_announcer",
        "GetOnNewFileItems",
        "sharepointonline",
        "dataset",
        "table",
        "folderPath",
        "connector_extension",
        "notification-details",
    ):
        assert expected in script
    assert "TEAMS_CHANNEL_ID" not in script
    assert "TEAMS_GROUP_ID" not in script
    assert "authorize-connectors" not in script
    assert "list-consent-links" not in script


@pytest.mark.parametrize("extension", ["sh", "ps1"])
def test_trigger_scripts_update_without_resetting_poll_history(extension: str) -> None:
    script = _read(f"configure-trigger.{extension}")

    assert "trigger show" in script
    assert '"update"' in script
    assert '"create"' in script
    assert "FORCE_CONNECTOR_TRIGGER_UPDATE" in script
    assert "leaving its polling state unchanged" in script
    assert "trigger delete" not in script


def test_connector_authorization_is_customer_managed_in_portal() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert not (SCRIPTS / "authorize-connectors.sh").exists()
    assert not (SCRIPTS / "authorize-connectors.ps1").exists()
    assert "https://connectors.azure.com/" in readme
    assert "sharepoint-document-source" in readme
    assert "teams-review-announcements" in readme


def test_callback_key_is_passed_through_a_temporary_file() -> None:
    shell_script = _read("configure-trigger.sh")
    powershell_script = _read("configure-trigger.ps1")

    assert '--notification-details "@${notificationFile}"' in shell_script
    assert '--notification-details "@$($notificationFile.FullName)"' in powershell_script
    assert '--arg value "$connectorKey"' not in shell_script
    assert '--arg callbackUrl "$callbackUrl"' not in shell_script
    assert "--notification-details \"$callbackUrl\"" not in shell_script
    assert "--notification-details $callbackUrl" not in powershell_script


def test_powershell_trigger_json_uses_utf8() -> None:
    powershell_script = _read("configure-trigger.ps1")

    assert powershell_script.count("-Encoding utf8") == 4
    assert "-Encoding ascii" not in powershell_script


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is unavailable")
def test_shell_scripts_parse() -> None:
    subprocess.run(
        ["bash", "-n", str(SCRIPTS / "configure-trigger.sh")],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell is unavailable")
def test_powershell_script_parses() -> None:
    script = str(SCRIPTS / "configure-trigger.ps1").replace("'", "''")
    command = (
        "$tokens = $null; $errors = $null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{script}', "
        "[ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { exit 1 }"
    )
    subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
    )
