import json

from lockin import policies


def patch_firefox_policy_paths(monkeypatch, tmp_path):
    policy_dir = tmp_path / "firefox" / "policies"
    policy_file = policy_dir / "policies.json"
    monkeypatch.setattr(policies, "FIREFOX_POLICY_DIR", policy_dir)
    monkeypatch.setattr(policies, "FIREFOX_POLICY_FILE", policy_file)

    def mkdir(path):
        path.mkdir(parents=True, exist_ok=True)

    def write(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def remove(path):
        path.unlink(missing_ok=True)

    monkeypatch.setattr(policies, "_sudo_mkdir", mkdir)
    monkeypatch.setattr(policies, "_sudo_write", write)
    monkeypatch.setattr(policies, "_sudo_remove", remove)
    return policy_dir, policy_file


def test_firefox_policy_clear_restores_existing_dns_policy(monkeypatch, tmp_path):
    _, policy_file = patch_firefox_policy_paths(monkeypatch, tmp_path)
    original = {
        "policies": {
            "DisableTelemetry": True,
            "DNSOverHTTPS": {"Enabled": True, "Locked": False},
        }
    }
    policy_file.parent.mkdir(parents=True)
    policy_file.write_text(json.dumps(original))

    policies._apply_firefox()
    policies._clear_firefox()

    assert json.loads(policy_file.read_text()) == original


def test_firefox_policy_clear_removes_file_created_by_lockin(monkeypatch, tmp_path):
    _, policy_file = patch_firefox_policy_paths(monkeypatch, tmp_path)

    policies._apply_firefox()
    policies._clear_firefox()

    assert not policy_file.exists()
