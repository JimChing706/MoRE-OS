import json
import asyncio
from typing import AsyncIterator, Literal
from openai import AsyncOpenAI
import anthropic

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import LLMConfig, ai_config

class LLMService:
    def __init__(self):
        self.openai_client = None
        self.anthropic_client = None
        self.lmstudio_client = None
        self.ollama_client = None
        self.lmstudio_available = True
        self.lmstudio_retry_count = 0
        self.max_retries = 3
        self.retry_delay = 2

    async def execute_task(
        self,
        task_type: str,
        query: str,
        context: dict | None = None
    ) -> dict:
        config = getattr(ai_config, task_type, ai_config.code_generation)

        if config.provider == "openai":
            return await self._call_openai(config, query, context)
        elif config.provider == "anthropic":
            return await self._call_anthropic(config, query, context)
        elif config.provider == "lmstudio":
            return await self._call_lmstudio_with_retry(config, query, context)
        elif config.provider == "ollama":
            return await self._call_ollama(config, query, context)
        else:
            raise ValueError(f"Unsupported provider: {config.provider}")

    async def _call_openai(self, config: LLMConfig, query: str, context: dict | None) -> dict:
        if not self.openai_client and config.api_key:
            self.openai_client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)

        if not self.openai_client:
            return await self._fallback_response(query)

        system_prompt = self._build_system_prompt(query, context)

        try:
            response = await self.openai_client.chat.completions.create(
                model=config.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ],
                max_tokens=config.max_tokens,
                temperature=config.temperature
            )

            return {
                "status": "success",
                "output": response.choices[0].message.content,
                "model": config.model,
                "provider": "openai",
                "tokens_used": response.usage.total_tokens if response.usage else 0
            }
        except Exception as e:
            return await self._fallback_response(query, str(e))

    async def _call_anthropic(self, config: LLMConfig, query: str, context: dict | None) -> dict:
        if not self.anthropic_client and config.api_key:
            self.anthropic_client = anthropic.AsyncAnthropic(api_key=config.api_key)

        if not self.anthropic_client:
            return await self._fallback_response(query)

        system_prompt = self._build_system_prompt(query, context)

        try:
            response = await self.anthropic_client.messages.create(
                model=config.model,
                max_tokens=config.max_tokens,
                temperature=config.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": query}]
            )

            return {
                "status": "success",
                "output": response.content[0].text,
                "model": config.model,
                "provider": "anthropic",
                "tokens_used": response.usage.input_tokens + response.usage.output_tokens
            }
        except Exception as e:
            return await self._fallback_response(query, str(e))

    async def _call_lmstudio_with_retry(self, config: LLMConfig, query: str, context: dict | None) -> dict:
        """LM Studio 调用，带自动重试机制"""
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                result = await self._call_lmstudio_internal(config, query, context)

                if result["status"] == "success":
                    self.lmstudio_available = True
                    self.lmstudio_retry_count = 0
                    return result

                if result["status"] == "unavailable":
                    last_error = result.get("output", "Unknown error")
                    self.lmstudio_available = False

                    if attempt < self.max_retries:
                        self.lmstudio_retry_count = attempt
                        print(f"[LM Studio] Attempt {attempt} failed, retrying in {self.retry_delay}s...")
                        await asyncio.sleep(self.retry_delay)
                        continue
                    else:
                        return result

                return result

            except Exception as e:
                last_error = str(e)
                self.lmstudio_available = False

                if attempt < self.max_retries:
                    print(f"[LM Studio] Error: {e}, retrying ({attempt}/{self.max_retries})...")
                    await asyncio.sleep(self.retry_delay)
                else:
                    print(f"[LM Studio] Max retries reached")

        return {
            "status": "unavailable",
            "output": f"[LM Studio 连接失败]\n\n尝试次数: {self.max_retries}\n\n错误信息: {last_error}\n\n请检查:\n1. LM Studio 是否已启动\n2. 是否已加载模型\n3. 是否启用了 API 服务\n4. 模型是否正在下载中",
            "model": config.model,
            "provider": "lmstudio",
            "tokens_used": 0,
            "retry_count": self.lmstudio_retry_count
        }

    async def _call_lmstudio_internal(self, config: LLMConfig, query: str, context: dict | None) -> dict:
        """LM Studio 内部调用"""
        if not self.lmstudio_client:
            base_url = config.base_url or "http://localhost:1234/v1"
            self.lmstudio_client = AsyncOpenAI(
                api_key="not-needed",
                base_url=base_url
            )

        system_prompt = self._build_system_prompt(query, context)

        try:
            response = await self.lmstudio_client.chat.completions.create(
                model=config.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ],
                max_tokens=config.max_tokens,
                temperature=config.temperature,
                stream=False
            )

            return {
                "status": "success",
                "output": response.choices[0].message.content,
                "model": config.model,
                "provider": "lmstudio",
                "tokens_used": response.usage.total_tokens if response.usage else 0
            }
        except Exception as e:
            error_msg = str(e)
            if "Connection" in error_msg or "refused" in error_msg.lower() or "ConnectError" in error_msg:
                return {
                    "status": "unavailable",
                    "output": f"[LM Studio 未运行]\n\n无法连接到 LM Studio (http://localhost:1234)\n\n请确保:\n1. LM Studio 已启动\n2. 已加载模型\n3. 已启用 API 服务 (设置中开启 \"API server\")\n\n错误: {error_msg}",
                    "model": config.model,
                    "provider": "lmstudio",
                    "tokens_used": 0
                }
            return {
                "status": "error",
                "output": f"[LM Studio 错误]\n\n{error_msg}",
                "model": config.model,
                "provider": "lmstudio",
                "tokens_used": 0
            }

    async def _call_ollama(self, config: LLMConfig, query: str, context: dict | None) -> dict:
        import httpx

        base_url = config.base_url or "http://localhost:11434"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{base_url}/api/generate",
                    json={
                        "model": config.model,
                        "prompt": f"{self._build_system_prompt(query, context)}\n\n{query}",
                        "stream": False
                    },
                    timeout=60.0
                )
                response.raise_for_status()
                data = response.json()

                return {
                    "status": "success",
                    "output": data.get("response", ""),
                    "model": config.model,
                    "provider": "ollama",
                    "tokens_used": data.get("eval_count", 0)
                }
        except Exception as e:
            return await self._fallback_response(query, str(e))

    async def _fallback_response(self, query: str, error: str | None = None) -> dict:
        return {
            "status": "simulated",
            "output": f"[Simulated response for: {query[:50]}...]\n\nThis is a simulated response.\n\nError: {error}" if error else f"[Simulated response for: {query[:50]}...]",
            "model": "simulated",
            "provider": "none",
            "tokens_used": 0
        }

    def _build_system_prompt(self, query: str, context: dict | None) -> str:
        base_prompt = """You are an expert AI assistant operating within the MoRE v3.0 (Multi-layer Reasoning Engine v3.0) system.

MoRE v3.0 Architecture:
- L5 (Metacognition): Self-monitoring, strategy selection, capability assessment
- L4 (Cognition): Task understanding, strategy evaluation, resource allocation
- L3 (Symbolic Reasoning): Ontology constraints, logical verification, rule engine
- L2 (Neural Evolution): DGM evolution, HyperAgent self-modification
- L1 (Orchestration): OMAC optimization, MARL training, dynamic routing
- L0 (Execution): Tool invocation, code execution, API interfaces

Your role is to process the given task through appropriate layers and provide high-quality outputs.

"""

        if context:
            base_prompt += f"\nContext:\n{json.dumps(context, ensure_ascii=False, indent=2)}\n"

        return base_prompt

    async def stream_execute(
        self,
        task_type: str,
        query: str,
        context: dict | None = None
    ) -> AsyncIterator[str]:
        config = getattr(ai_config, task_type, ai_config.code_generation)

        if config.provider == "openai":
            async for chunk in self._stream_openai(config, query, context):
                yield chunk
        elif config.provider == "anthropic":
            async for chunk in self._stream_anthropic(config, query, context):
                yield chunk
        elif config.provider == "lmstudio":
            async for chunk in self._stream_lmstudio_with_retry(config, query, context):
                yield chunk
        elif config.provider == "ollama":
            async for chunk in self._stream_ollama(config, query, context):
                yield chunk
        else:
            yield "[Simulated streaming response]"

    async def _stream_openai(self, config: LLMConfig, query: str, context: dict | None) -> AsyncIterator[str]:
        if not self.openai_client and config.api_key:
            self.openai_client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)

        if not self.openai_client:
            yield await self._fallback_response(query)["output"]
            return

        try:
            stream = await self.openai_client.chat.completions.create(
                model=config.model,
                messages=[
                    {"role": "system", "content": self._build_system_prompt(query, context)},
                    {"role": "user", "content": query}
                ],
                max_tokens=config.max_tokens,
                temperature=config.temperature,
                stream=True
            )

            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            yield f"Error: {str(e)}"

    async def _stream_anthropic(self, config: LLMConfig, query: str, context: dict | None) -> AsyncIterator[str]:
        if not self.anthropic_client and config.api_key:
            self.anthropic_client = anthropic.AsyncAnthropic(api_key=config.api_key)

        if not self.anthropic_client:
            yield await self._fallback_response(query)["output"]
            return

        try:
            async with self.anthropic_client.messages.stream(
                model=config.model,
                max_tokens=config.max_tokens,
                temperature=config.temperature,
                system=self._build_system_prompt(query, context),
                messages=[{"role": "user", "content": query}]
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as e:
            yield f"Error: {str(e)}"

    async def _stream_lmstudio_with_retry(self, config: LLMConfig, query: str, context: dict | None) -> AsyncIterator[str]:
        """流式 LM Studio 调用，带重试"""
        for attempt in range(1, self.max_retries + 1):
            try:
                async for chunk in self._stream_lmstudio_internal(config, query, context):
                    yield chunk
                return
            except Exception as e:
                if attempt < self.max_retries:
                    print(f"[LM Studio Stream] Error: {e}, retrying ({attempt}/{self.max_retries})...")
                    await asyncio.sleep(self.retry_delay)
                else:
                    yield f"[LM Studio 连接失败，已重试 {self.max_retries} 次]"

    async def _stream_lmstudio_internal(self, config: LLMConfig, query: str, context: dict | None) -> AsyncIterator[str]:
        """LM Studio 流式内部调用"""
        if not self.lmstudio_client:
            base_url = config.base_url or "http://localhost:1234/v1"
            self.lmstudio_client = AsyncOpenAI(
                api_key="not-needed",
                base_url=base_url
            )

        try:
            stream = await self.lmstudio_client.chat.completions.create(
                model=config.model,
                messages=[
                    {"role": "system", "content": self._build_system_prompt(query, context)},
                    {"role": "user", "content": query}
                ],
                max_tokens=config.max_tokens,
                temperature=config.temperature,
                stream=True
            )

            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            error_msg = str(e)
            if "Connection" in error_msg or "refused" in error_msg.lower() or "ConnectError" in error_msg:
                raise ConnectionError("[LM Studio 未运行，请确保 LM Studio 已启动并启用 API 服务]")
            raise Exception(error_msg)

    async def _stream_ollama(self, config: LLMConfig, query: str, context: dict | None) -> AsyncIterator[str]:
        import httpx

        base_url = config.base_url or "http://localhost:11434"

        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    f"{base_url}/api/generate",
                    json={
                        "model": config.model,
                        "prompt": f"{self._build_system_prompt(query, context)}\n\n{query}",
                        "stream": True
                    },
                    timeout=60.0
                ) as stream:
                    async for line in stream.aiter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                if "response" in data:
                                    yield data["response"]
                            except json.JSONDecodeError:
                                continue
        except Exception as e:
            yield f"Error: {str(e)}"

    def get_lmstudio_status(self) -> dict:
        """获取 LM Studio 连接状态"""
        return {
            "available": self.lmstudio_available,
            "retry_count": self.lmstudio_retry_count,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay
        }

llm_service = LLMService()
