#!/usr/bin/env python3
"""Quick test for Qwen3.8-27B via llama.cpp or Ollama.

Usage:
    python3 scripts/test-qwen38.py [llamacpp|ollama]
"""
import asyncio
import httpx
import sys

ENDPOINTS = {
    "llamacpp": "http://localhost:8090/v1/chat/completions",
    "ollama": "http://localhost:11434/api/chat",
}
MODEL = "qwen3.8-27b"


async def test_llamacpp() -> None:
    url = ENDPOINTS["llamacpp"]
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "用一句话介绍你自己"}],
        "max_tokens": 128,
        "temperature": 0.7,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        print(f"[llamacpp] Response: {text}")
        print(
            f"[llamacpp] Tokens: prompt={usage.get('prompt_tokens', 0)}, "
            f"completion={usage.get('completion_tokens', 0)}"
        )


async def test_ollama() -> None:
    url = ENDPOINTS["ollama"]
    payload = {
        "model": "hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q6_K",
        "messages": [{"role": "user", "content": "用一句话介绍你自己"}],
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
        text = data.get("message", {}).get("content", "")
        print(f"[ollama] Response: {text}")


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "llamacpp"
    if mode == "llamacpp":
        await test_llamacpp()
    elif mode == "ollama":
        await test_ollama()
    else:
        print(f"Usage: {sys.argv[0]} [llamacpp|ollama]")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
