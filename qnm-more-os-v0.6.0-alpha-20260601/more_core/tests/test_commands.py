"""Tests for the Slash Command Registry."""

from more_core.commands.registry import CommandRegistry, Command, CommandSurface, register_builtin_commands


def test_register_and_get():
    reg = CommandRegistry()
    cmd = Command(name="test", description="test command")
    reg.register(cmd)
    assert reg.get("test") is cmd


def test_alias_resolution():
    reg = CommandRegistry()
    cmd = Command(name="help", description="help", aliases=["h", "?"])
    reg.register(cmd)
    assert reg.get("h") is cmd
    assert reg.get("?") is cmd
    assert reg.get("help") is cmd


def test_list_by_surface():
    reg = CommandRegistry()
    reg.register(Command(name="cli_only", description="a", surfaces=CommandSurface.CLI))
    reg.register(Command(name="web_only", description="b", surfaces=CommandSurface.WEB))
    reg.register(Command(name="both", description="c", surfaces=CommandSurface.ALL))
    cli_cmds = reg.list_commands(surface=CommandSurface.CLI)
    names = [c.name for c in cli_cmds]
    assert "cli_only" in names
    assert "both" in names
    assert "web_only" not in names


def test_list_by_category():
    reg = CommandRegistry()
    reg.register(Command(name="a", description="a", category="system"))
    reg.register(Command(name="b", description="b", category="tools"))
    assert len(reg.list_commands(category="system")) == 1


def test_builtin_commands():
    reg = CommandRegistry()
    register_builtin_commands(reg)
    assert reg.get("help") is not None
    assert reg.get("hand") is not None
    assert reg.get("task") is not None
    assert reg.get("zen") is not None
    # Check aliases
    assert reg.get("h") is not None  # alias for help
    assert reg.get("hands") is not None  # alias for hand
    assert reg.get("run") is not None  # alias for task
    stats = reg.stats()
    assert stats["total_commands"] >= 14


def test_to_api_dict():
    reg = CommandRegistry()
    register_builtin_commands(reg)
    api_data = reg.to_api_dict()
    assert isinstance(api_data, list)
    assert all("name" in c for c in api_data)
    assert all("description" in c for c in api_data)


def test_help_text():
    reg = CommandRegistry()
    reg.register(Command(name="foo", description="bar"))
    text = reg.help_text()
    assert "/foo" in text
    assert "bar" in text


def test_unregister():
    reg = CommandRegistry()
    reg.register(Command(name="tmp", description="temp", aliases=["t"]))
    reg.unregister("tmp")
    assert reg.get("tmp") is None
    assert reg.get("t") is None
