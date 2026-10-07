import pytest

from more_core.core.errors import MoREError
from more_core.core.service_registry import ServiceRegistry
from more_core.core.types import EngineStatus, ServiceMetadata


def test_register_and_discover() -> None:
    reg = ServiceRegistry()
    md = ServiceMetadata(name="svc", version="1.0.0", provider="core", status=EngineStatus.RUNNING)
    reg.register(md)
    assert reg.get("svc") is md
    assert reg.list_by_provider("core") == [md]


def test_duplicate_registration_rejected() -> None:
    reg = ServiceRegistry()
    md = ServiceMetadata(name="svc", version="1", provider="core")
    reg.register(md)
    with pytest.raises(MoREError):
        reg.register(md)


def test_unregister() -> None:
    reg = ServiceRegistry()
    md = ServiceMetadata(name="svc", version="1", provider="core")
    reg.register(md)
    reg.unregister("svc")
    assert reg.get("svc") is None


def test_set_status_updates_registered_service() -> None:
    reg = ServiceRegistry()
    md = ServiceMetadata(name="svc", version="1", provider="core")
    reg.register(md)
    assert reg.set_status("svc", EngineStatus.RUNNING) is True
    assert reg.get("svc").status == EngineStatus.RUNNING  # type: ignore[union-attr]


def test_set_status_unknown_returns_false() -> None:
    reg = ServiceRegistry()
    assert reg.set_status("ghost", EngineStatus.RUNNING) is False
