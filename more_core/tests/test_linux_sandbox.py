"""Tests for sandbox factory and LinuxSandbox platform detection."""

import sys

from more_core.sandbox.linux_sandbox import create_sandbox, is_linux, LinuxSandbox
from more_core.sandbox.subprocess_sandbox import SubprocessSandbox


def test_is_linux_on_current_platform():
    """is_linux() should match sys.platform."""
    expected = sys.platform.startswith("linux")
    assert is_linux() == expected


def test_create_sandbox_returns_correct_type():
    """On macOS returns SubprocessSandbox, on Linux returns LinuxSandbox."""
    sandbox = create_sandbox()
    if is_linux():
        assert isinstance(sandbox, LinuxSandbox)
    else:
        assert isinstance(sandbox, SubprocessSandbox)
        assert not isinstance(sandbox, LinuxSandbox)


def test_linux_sandbox_inherits_subprocess():
    """LinuxSandbox inherits from SubprocessSandbox."""
    assert issubclass(LinuxSandbox, SubprocessSandbox)
