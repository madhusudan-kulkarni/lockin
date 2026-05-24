import importlib
import json
import sys


def import_watchdog(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCKIN_STATE", str(tmp_path / "state.json"))
    sys.modules.pop("lockin.watchdog", None)
    return importlib.import_module("lockin.watchdog")


def test_watchdog_firefox_policy_clear_preserves_existing_policies(
    monkeypatch, tmp_path
):
    watchdog = import_watchdog(monkeypatch, tmp_path)
    firefox_dir = tmp_path / "firefox" / "policies"
    firefox_dir.mkdir(parents=True)
    policies_file = firefox_dir / "policies.json"
    policies_file.write_text(
        json.dumps(
            {
                "policies": {
                    "DisableTelemetry": True,
                    "DNSOverHTTPS": {"Enabled": False, "Locked": True},
                    "LockinManaged": True,
                }
            }
        )
    )
    monkeypatch.setattr(watchdog, "POLICY_DIRS", [firefox_dir])

    watchdog._clear_policies()

    assert json.loads(policies_file.read_text()) == {
        "policies": {"DisableTelemetry": True}
    }


def test_watchdog_firefox_policy_clear_restores_backup(monkeypatch, tmp_path):
    watchdog = import_watchdog(monkeypatch, tmp_path)
    firefox_dir = tmp_path / "firefox" / "policies"
    firefox_dir.mkdir(parents=True)
    policies_file = firefox_dir / "policies.json"
    backup_file = firefox_dir / "policies.json.lockin-backup"
    original = {
        "policies": {
            "DisableTelemetry": True,
            "DNSOverHTTPS": {"Enabled": True, "Locked": False},
        }
    }
    policies_file.write_text(
        json.dumps(
            {
                "policies": {
                    "DisableTelemetry": True,
                    "DNSOverHTTPS": {"Enabled": False, "Locked": True},
                    "LockinManaged": True,
                }
            }
        )
    )
    backup_file.write_text(json.dumps(original))
    monkeypatch.setattr(watchdog, "POLICY_DIRS", [firefox_dir])

    watchdog._clear_policies()

    assert json.loads(policies_file.read_text()) == original
    assert not backup_file.exists()


def test_watchdog_firefox_policy_clear_removes_file_when_backup_was_empty(
    monkeypatch, tmp_path
):
    watchdog = import_watchdog(monkeypatch, tmp_path)
    firefox_dir = tmp_path / "firefox" / "policies"
    firefox_dir.mkdir(parents=True)
    policies_file = firefox_dir / "policies.json"
    backup_file = firefox_dir / "policies.json.lockin-backup"
    policies_file.write_text(
        json.dumps({"policies": {"DNSOverHTTPS": {"Enabled": False}}})
    )
    backup_file.write_text("")
    monkeypatch.setattr(watchdog, "POLICY_DIRS", [firefox_dir])

    watchdog._clear_policies()

    assert not policies_file.exists()
    assert not backup_file.exists()


def test_watchdog_firefox_policy_clear_removes_empty_lockin_file(
    monkeypatch, tmp_path
):
    watchdog = import_watchdog(monkeypatch, tmp_path)
    firefox_dir = tmp_path / "firefox" / "policies"
    firefox_dir.mkdir(parents=True)
    policies_file = firefox_dir / "policies.json"
    policies_file.write_text(
        json.dumps(
            {
                "policies": {
                    "DNSOverHTTPS": {"Enabled": False, "Locked": True},
                    "LockinManaged": True,
                }
            }
        )
    )
    monkeypatch.setattr(watchdog, "POLICY_DIRS", [firefox_dir])

    watchdog._clear_policies()

    assert not policies_file.exists()
