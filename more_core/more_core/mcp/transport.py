"""MCP Transport implementations - stdio, SSE, HTTP."""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, cast

from ..core.errors import MCPError
from .protocol import MCPMessage, JSONRPCProtocol

_log = logging.getLogger(__name__)


class _StdoutProtocol(asyncio.Protocol):
    """Minimal protocol for creating a StreamWriter to stdout.

    Replaces the removed ``asyncio.StreamWriterProtocol`` (Python 3.14+).
    """

    def __init__(self) -> None:
        self._transport: asyncio.BaseTransport | None = None
        self._closed = asyncio.Event()

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport

    def connection_lost(self, exc: Exception | None) -> None:
        self._closed.set()


class Transport(ABC):
    """Base transport class."""

    @abstractmethod
    async def connect(self) -> None:
        """Connect to the transport."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the transport."""
        pass

    @abstractmethod
    async def send(self, message: str) -> None:
        """Send a message."""
        pass

    @abstractmethod
    async def receive(self) -> str:
        """Receive a message."""
        pass


class StdioTransport(Transport):
    """Stdio transport for local process communication."""

    def __init__(self) -> None:
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._protocol = JSONRPCProtocol()

    async def connect(self) -> None:
        """Connect to stdio."""
        import sys

        loop = asyncio.get_running_loop()
        self._reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(self._reader)

        await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)

        writer_protocol = _StdoutProtocol()
        writer_transport, _ = await loop.create_connection(  # type: ignore[call-overload]
            lambda: writer_protocol,
            None,
            None,
        )
        self._writer = asyncio.StreamWriter(writer_transport, writer_protocol, None, loop)

        _log.info("Stdio transport connected")

    async def disconnect(self) -> None:
        """Disconnect from stdio."""
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
        _log.info("Stdio transport disconnected")

    async def send(self, message: str) -> None:
        """Send message via stdio."""
        if self._writer:
            self._writer.write((message + "\n").encode("utf-8"))
            await self._writer.drain()

    async def receive(self) -> str:
        """Receive message from stdio."""
        if self._reader:
            line = await self._reader.readline()
            return line.decode("utf-8").strip()
        return ""


class HTTPTransport(Transport):
    """HTTP transport for remote MCP communication."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._session: Any = None
        self._protocol = JSONRPCProtocol()

    async def connect(self) -> None:
        """Connect via HTTP."""
        try:
            import aiohttp

            self._session = aiohttp.ClientSession()
            _log.info(f"HTTP transport connected to {self._base_url}")
        except ImportError:
            _log.warning("aiohttp not installed, HTTP transport unavailable")

    async def disconnect(self) -> None:
        """Disconnect from HTTP."""
        if self._session:
            await self._session.close()
        _log.info("HTTP transport disconnected")

    async def send(self, message: str) -> None:
        """Send message via HTTP POST."""
        if not self._session:
            raise MCPError("HTTP session not connected")

        msg = self._protocol.parse_message(message)
        if not isinstance(msg, MCPMessage):
            return

        async with self._session.post(
            f"{self._base_url}/mcp",
            json={
                "jsonrpc": "2.0",
                "method": cast(Any, msg).method,
                "params": cast(Any, msg).params,
                "id": msg.id,
            },
        ) as response:
            await response.json()

    async def receive(self) -> str:
        """Receive message via HTTP (polling)."""
        raise NotImplementedError("HTTP transport uses async polling, not receive()")


class SSESTransport(Transport):
    """Server-Sent Events transport for streaming responses."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._session: Any = None
        self._event_queue: asyncio.Queue[str] = asyncio.Queue()

    async def connect(self) -> None:
        """Connect via SSE."""
        try:
            import aiohttp

            self._session = aiohttp.ClientSession()
            _log.info(f"SSE transport connected to {self._base_url}")
        except ImportError:
            _log.warning("aiohttp not installed, SSE transport unavailable")

    async def disconnect(self) -> None:
        """Disconnect from SSE."""
        if self._session:
            await self._session.close()
        _log.info("SSE transport disconnected")

    async def send(self, message: str) -> None:
        """Send message via HTTP POST."""
        if not self._session:
            raise MCPError("SSE session not connected")

        async with self._session.post(
            f"{self._base_url}/mcp",
            json=json.loads(message),
        ) as response:
            result = await response.json()
            await self._event_queue.put(json.dumps(result))

    async def receive(self) -> str:
        """Receive message from event queue."""
        return await self._event_queue.get()

    async def events(self) -> asyncio.Queue[str]:
        """Get event queue for streaming."""
        return self._event_queue


class ProcessTransport(Transport):
    """Transport that spawns a subprocess."""

    def __init__(self, command: list[str], env: dict[str, str] | None = None) -> None:
        self._command = command
        self._env = env
        self._process: asyncio.subprocess.Process | None = None
        self._protocol = JSONRPCProtocol()

    async def connect(self) -> None:
        """Spawn and connect to subprocess."""
        self._process = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
        )
        _log.info(f"Process transport started: {' '.join(self._command)}")

    async def disconnect(self) -> None:
        """Terminate subprocess."""
        if self._process:
            self._process.terminate()
            await self._process.wait()
        _log.info("Process transport stopped")

    async def send(self, message: str) -> None:
        """Send message to subprocess."""
        if self._process and self._process.stdin:
            self._process.stdin.write((message + "\n").encode("utf-8"))
            await self._process.stdin.drain()

    async def receive(self) -> str:
        """Receive message from subprocess."""
        if self._process and self._process.stdout:
            line = await self._process.stdout.readline()
            return line.decode("utf-8").strip()
        return ""


async def create_stdio_transport() -> StdioTransport:
    """Create and connect stdio transport."""
    transport = StdioTransport()
    await transport.connect()
    return transport


async def create_process_transport(
    command: list[str], env: dict[str, str] | None = None
) -> ProcessTransport:
    """Create and connect process transport."""
    transport = ProcessTransport(command, env)
    await transport.connect()
    return transport


async def create_http_transport(base_url: str) -> HTTPTransport:
    """Create and connect HTTP transport."""
    transport = HTTPTransport(base_url)
    await transport.connect()
    return transport
