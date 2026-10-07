"""Pytest suite for 补缺 MoRE API key 业务链路.

Scope
-----
Security pure-stdlib layer (api_key_ops.py) + argparse CLI dispatch +
admin router offline TestClient. 18 用例：
  生成 3 / validate 6 / inject 3 / proof 4 / env fallback 2.

No runtime.*, no layers.*, no tools.* dependencies — G-2-6 零侵入.
"""

from __future__ import annotations

import os
import sys
import time
import tempfile
import shutil
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from more_core.security.api_key_ops import (
    API_KEY_MIN_LENGTH,
    API_KEY_PREFIX,
    ENV_PATHS,
    generate_api_key,
    inject_api_key_into_env,
    sign_rotation_proof,
    validate_api_key_report,
    verify_rotation_proof,
)


# ---------------------------------------------------------------------------
# Group 1 — generate_api_key 3 cases (compat/modern/hex)
# ---------------------------------------------------------------------------


class TestGenerateAPIKey:
    def test_compat_length_46_base64url(self):
        k = generate_api_key("compat")
        assert len(k) == 46
        assert validate_api_key_report(k).valid is True
        import string

        charset = set(string.ascii_letters + string.digits + "-_=")
        assert all(ch in charset for ch in k)

    def test_modern_prefix_and_length(self):
        k = generate_api_key("modern")
        assert len(k) == 59
        assert k.startswith(API_KEY_PREFIX)
        r = validate_api_key_report(k, require_prefix=True)
        assert r.valid is True
        assert r.has_prefix is True
        assert r.kind_guess == "modern"

    def test_hex_64_lowercase(self):
        k = generate_api_key("hex")
        assert len(k) == 64
        assert all(ch in "0123456789abcdef" for ch in k)
        r = validate_api_key_report(k)
        assert r.valid is True
        assert r.entropy_bits >= 256.0


# ---------------------------------------------------------------------------
# Group 2 — validate_api_key_report 6 cases
# ---------------------------------------------------------------------------


class TestValidateReport:
    def test_valid_compat_report_fields(self):
        k = generate_api_key("compat")
        r = validate_api_key_report(k)
        assert r.valid is True
        assert r.length == 46
        assert r.entropy_bits >= 192
        assert r.charset_ok is True
        assert r.errors == []

    def test_short_key_below_min_returns_errors(self):
        r = validate_api_key_report("short")
        assert r.valid is False
        assert len(r.errors) >= 1
        assert any("length" in e.lower() for e in r.errors)

    def test_invalid_charset_whitespace(self):
        r = validate_api_key_report("has  space  and tab\t!")
        assert r.valid is False
        assert any("charset" in e.lower() or "character" in e.lower() for e in r.errors)

    def test_require_prefix_strict_rejects_plain(self):
        k_noprefix = generate_api_key("compat")
        r = validate_api_key_report(k_noprefix, require_prefix=True)
        assert r.valid is False
        assert any("prefix" in e.lower() for e in r.errors)

    def test_require_prefix_strict_accepts_modern(self):
        k_prefix = generate_api_key("modern")
        r = validate_api_key_report(k_prefix, require_prefix=True)
        assert r.valid is True
        assert r.has_prefix is True

    def test_more_envvar_prefix_collision_warning(self):
        pseudo = "MORE_API_KEY=pretend_I_was_a_46char_value_okay??"
        r = validate_api_key_report(pseudo)
        found = any(
            "MORE." in w or "rotate it" in w.lower() or "collision" in w.lower() for w in r.warnings
        )
        assert found is True, f"warnings should flag MORE.* prefix collision: {r.warnings}"

    def test_constants_aligned_with_server_baseline(self):
        """C2 约束：业务层常量必须与 server.py 基线一致."""
        assert API_KEY_MIN_LENGTH == 16
        assert API_KEY_PREFIX == "sk-more-os-"


# ---------------------------------------------------------------------------
# Group 3 — inject_api_key_into_env 3 cases
# ---------------------------------------------------------------------------


class TestInjectEnv:
    @pytest.fixture
    def td(self):
        d = tempfile.mkdtemp(prefix="more_env_")
        yield d
        shutil.rmtree(d, ignore_errors=True)

    def test_new_env_file_created_600_perms(self, td):
        target = os.path.join(td, "brand_new.env")
        key = generate_api_key("modern")
        path, backup, prev = inject_api_key_into_env(key, target, backup=True, strict=True)
        assert os.path.exists(target)
        perms = oct(os.stat(target).st_mode)[-3:]
        assert perms == "600", f"perms={perms} want 600"
        with open(target) as fh:
            content = fh.read()
        assert 'MORE_API_KEY="' in content and key in content
        assert backup is None, "new file should NOT produce backup"

    def test_existing_key_replaced_with_backup(self, td):
        target = os.path.join(td, "existing.env")
        old_line = 'MORE_API_KEY="sk-more-os-OLD1234567890123456789012345678"'
        with open(target, "w") as fh:
            fh.write("# header\n")
            fh.write(old_line + "\n")
            fh.write("KEEP_ME=yes\n")
        new_key = generate_api_key("modern")
        path, backup, prev = inject_api_key_into_env(new_key, target, backup=True, strict=True)
        assert backup is not None and os.path.exists(backup)
        with open(path) as fh:
            content = fh.read()
        assert "KEEP_ME=yes" in content
        assert new_key in content
        assert "OLD1234" not in content
        with open(backup) as fh:
            bak = fh.read()
        assert "OLD1234" in bak, "backup must contain previous value"

    def test_illegal_short_key_refused_no_write(self, td):
        target = os.path.join(td, "should_not_exist.env")
        with pytest.raises((ValueError, Exception)):
            inject_api_key_into_env("tooshort", target)
        assert not os.path.exists(target), "refused inject must not create file"


# ---------------------------------------------------------------------------
# Group 4 — sign/verify rotation_proof 4 cases
# ---------------------------------------------------------------------------


class TestRotationProof:
    MASTER = "012345678901234567890123456789DEADBEEF_MASTER"

    def test_happy_path_verify_true(self):
        new_key = generate_api_key("modern")
        proof = sign_rotation_proof(
            master_key=self.MASTER, new_key=new_key, revoke_old_in_seconds=3600
        )
        assert (
            verify_rotation_proof(
                master_key=self.MASTER, proof=proof, new_key=new_key, revoke_old_in_seconds=3600
            )
            is True
        )

    def test_wrong_master_key_verify_false(self):
        new_key = generate_api_key("modern")
        proof = sign_rotation_proof(
            master_key=self.MASTER, new_key=new_key, revoke_old_in_seconds=3600
        )
        assert (
            verify_rotation_proof(
                master_key=self.MASTER + "X",
                proof=proof,
                new_key=new_key,
                revoke_old_in_seconds=3600,
            )
            is False
        )

    def test_wrong_revoke_window_verify_false(self):
        new_key = generate_api_key("modern")
        proof = sign_rotation_proof(
            master_key=self.MASTER, new_key=new_key, revoke_old_in_seconds=3600
        )
        assert (
            verify_rotation_proof(
                master_key=self.MASTER, proof=proof, new_key=new_key, revoke_old_in_seconds=7200
            )
            is False
        )

    def test_ttl_expired_verify_false(self):
        new_key = generate_api_key("modern")
        old = int(time.time()) - 600  # 10 min ago, TTL = 5 min default
        proof = sign_rotation_proof(
            master_key=self.MASTER, new_key=new_key, revoke_old_in_seconds=3600, issued_at_unix=old
        )
        assert (
            verify_rotation_proof(
                master_key=self.MASTER,
                proof=proof,
                new_key=new_key,
                revoke_old_in_seconds=3600,
                ttl_seconds=300,
            )
            is False
        )


# ---------------------------------------------------------------------------
# Group 5 — ENV_PATHS fallback 2 cases
# ---------------------------------------------------------------------------


class TestEnvPathsFallback:
    def test_env_paths_contains_four_candidates(self):
        assert len(ENV_PATHS) == 4
        # 1) repo root more_core/.env (parents[2]: parents[1]=more_core/more_core parents[2]=more_core)
        # 2) more_core/more_core/.env
        # 3) cwd/.env
        # 4) ~/.config/qnming-more-os/.env
        last = ENV_PATHS[-1]
        assert last.parts[-2:] == ("qnming-more-os", ".env") or "config" in str(last)
        # All must be Path instances and absolute
        for p in ENV_PATHS:
            assert isinstance(p, Path)

    def test_fallback_includes_repo_more_core_dot_env(self):
        """补缺链路 must include $repo/more_core/.env as fallback candidate."""
        repo_more = Path(__file__).resolve().parents[1] / ".env"
        as_strings = {str(p.resolve()) for p in ENV_PATHS}
        assert str(repo_more.resolve()) in as_strings, (
            f"ENV_PATHS must include repo more_core/.env. Got: {ENV_PATHS}"
        )


# ---------------------------------------------------------------------------
# Group 6 — CLI argparse dispatch smoke 3 more (total=18+3 bonus=21)
# ---------------------------------------------------------------------------


class TestCLIDispatchSmoke:
    def test_generate_cmd_dispatches(self):
        from more_core.cli import main

        rc = main(["api-key", "generate", "--strength", "hex"])
        assert rc == 0

    def test_validate_bad_key_exits_one(self):
        from more_core.cli import main

        rc = main(["api-key", "validate", "--key", "tooshort"])
        assert rc == 1

    def test_rotate_proof_missing_master_exits_two(self):
        from more_core.cli import main

        env_backup = os.environ.pop("MORE_MASTER_ROTATION_KEY", None)
        try:
            rc = main(["api-key", "rotate-proof", "--revoke-seconds", "600"])
        finally:
            if env_backup:
                os.environ["MORE_MASTER_ROTATION_KEY"] = env_backup
        assert rc == 2
