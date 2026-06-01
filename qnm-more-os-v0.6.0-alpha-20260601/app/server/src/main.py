#!/usr/bin/env python3
"""QNMing MoRE OS — Dashboard BFF Server.

Thin proxy that delegates all task execution to the real ``more_core``
kernel.  No simulated data — every reasoning step, token count, and
confidence value comes from the L0–L5 pipeline.
"""

import hmac
import json
import os
import time
from typing import Any
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from .services.redis_state import redis_state_manager

# ---------------------------------------------------------------------------
# more_core kernel imports
# ---------------------------------------------------------------------------
from more_core.core.config import Settings, LLMProviderConfig
from more_core.core.types import (
    TaskRequest as CoreTaskRequest,
    TaskResult as CoreTaskResult,
    TaskType,
    LayerId,
)
from more_core.runtime.orchestrator import MoRECore

# ---------------------------------------------------------------------------
# BFF request / response models (kept compatible with frontend)
# ---------------------------------------------------------------------------

class TaskRequest(BaseModel):
    type: str = "nlp_task"
    query: str
    context: dict | None = None
    require_metacognitive_monitoring: bool = False
    allow_self_improvement: bool = False
    target_layer: str | None = None
    timeout_s: float = 60.0


class ReasoningStep(BaseModel):
    id: int
    layer: str
    description: str
    duration: int
    confidence: float
    input_tokens: int = 0
    output_tokens: int = 0
    timestamp: float = 0.0


class TaskResponse(BaseModel):
    task_id: str
    layer: str
    status: str
    output: str
    reasoning_chain: list[ReasoningStep]
    performance: dict
    calibration: dict | None = None
    metadata: dict | None = None


TASK_TYPE_LABELS = {
    "code_generation": "代码生成",
    "code_debugging": "代码调试",
    "code_testing": "代码测试",
    "math_reasoning": "数学推理",
    "data_analysis": "数据分析",
    "nlp_task": "NLP任务",
    "multi_agent_orchestration": "Agent编排",
    "self_improvement": "自我改进",
    "cross_domain_transfer": "跨域迁移",
    "code_review": "代码审查",
    "architecture_design": "架构设计",
}

# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket

    def disconnect(self, client_id: str):
        self.active_connections.pop(client_id, None)

    async def send_personal_message(self, message: dict, client_id: str):
        ws = self.active_connections.get(client_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                pass

    async def broadcast(self, message: dict):
        for ws in list(self.active_connections.values()):
            try:
                await ws.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()
task_history: list[dict] = []
core: MoRECore | None = None

TASK_HISTORY_KEY = "more:v3:task_history"
MAX_TASK_HISTORY = 100
REDIS_TASK_EXPIRE = 86400 * 7

# ---------------------------------------------------------------------------
# Build Settings from BFF .env (bridge BFF env vars → more_core Settings)
# ---------------------------------------------------------------------------

def _build_core_settings() -> Settings:
    """Construct more_core Settings from BFF environment variables."""
    from dotenv import load_dotenv
    load_dotenv()

    providers: list[LLMProviderConfig] = []

    # LM Studio (primary for BFF)
    lm_url = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
    lm_model = os.getenv("LMSTUDIO_MODEL", "gemma-4-coder")
    providers.append(LLMProviderConfig(
        name="lmstudio",
        provider="lmstudio",
        endpoint=lm_url,
        model=lm_model,
    ))

    # Ollama (optional)
    ollama_url = os.getenv("OLLAMA_BASE_URL", "")
    if ollama_url:
        providers.append(LLMProviderConfig(
            name="ollama",
            provider="ollama",
            endpoint=ollama_url,
            model=os.getenv("OLLAMA_MODEL", "llama2"),
        ))

    # OpenAI-compat (optional)
    oai_key = os.getenv("OPENAI_API_KEY", "")
    if oai_key and not oai_key.startswith("your-"):
        providers.append(LLMProviderConfig(
            name="openai",
            provider="openai",
            endpoint=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            api_key=oai_key,
        ))

    fallback_chain = [p.name for p in providers]

    return Settings(
        plugin_dir=os.getenv("MORE_PLUGIN_DIR", "plugins"),
        log_dir=os.getenv("MORE_LOG_DIR", "logs"),
        providers=providers,
        fallback_chain=fallback_chain,
        enable_evolution=os.getenv("MORE_ENABLE_EVOLUTION", "0") == "1",
        enable_metacognition=os.getenv("MORE_ENABLE_METACOGNITION", "0") == "1",
        enable_symbolic=os.getenv("MORE_ENABLE_SYMBOLIC", "1") == "1",
    )

# ---------------------------------------------------------------------------
# Convert core TaskResult → BFF response dict
# ---------------------------------------------------------------------------

def _core_result_to_dict(result: CoreTaskResult, task_type: str) -> dict:
    """Convert a real kernel TaskResult to the shape the frontend expects."""
    chain = []
    for step in result.reasoning_chain:
        chain.append({
            "id": step.id,
            "layer": step.layer.value if hasattr(step.layer, "value") else str(step.layer),
            "description": step.description,
            "duration": int(step.duration_ms),
            "input_tokens": step.input_tokens,
            "output_tokens": step.output_tokens,
            "confidence": step.confidence,
            "timestamp": int(step.timestamp * 1000) if step.timestamp else int(time.time() * 1000),
        })

    perf = {
        "total_duration": int(result.performance.total_duration_ms),
        "tokens_used": result.performance.tokens_used,
        "layer_transitions": result.performance.layer_transitions,
    }

    return {
        "task_id": result.task_id,
        "layer": result.layer.value if hasattr(result.layer, "value") else str(result.layer),
        "status": result.status.value if hasattr(result.status, "value") else str(result.status),
        "output": result.output,
        "reasoning_chain": chain,
        "performance": perf,
        "calibration": result.calibration,
        "metadata": {
            "task_type": task_type,
            "task_label": TASK_TYPE_LABELS.get(task_type, task_type),
            "kernel": "more_core",
            **(result.metadata or {}),
        },
    }

# ---------------------------------------------------------------------------
# Real task execution via more_core kernel
# ---------------------------------------------------------------------------

async def execute_task_real(
    request: TaskRequest,
    client_id: str | None = None,
) -> dict:
    """Execute a task through the real more_core L0-L5 pipeline."""
    global core
    if core is None:
        raise RuntimeError("MoRECore not initialised")

    # Build core TaskRequest
    target = LayerId(request.target_layer) if request.target_layer else None
    task_type_str = request.type
    try:
        task_type = TaskType(task_type_str)
    except ValueError:
        task_type = TaskType.NLP_TASK

    core_req = CoreTaskRequest(
        type=task_type,
        query=request.query,
        context=request.context or {},
        target_layer=target,
        require_metacognitive_monitoring=request.require_metacognitive_monitoring,
        allow_self_improvement=request.allow_self_improvement,
        timeout_s=request.timeout_s,
    )

    # Subscribe to layer events for real-time WebSocket relay
    relay_queue = None
    unsub = None
    if client_id:
        import asyncio
        relay_queue = asyncio.Queue()

        async def _on_layer_completed(event) -> None:
            data = event.data if hasattr(event, "data") else event
            if isinstance(data, dict) and data.get("task_id") == core_req.id:
                await relay_queue.put(data)

        unsub = core.event_bus.subscribe("layer.completed", _on_layer_completed)

    # Execute through real kernel
    try:
        result = await core.execute(core_req)
    finally:
        if unsub:
            unsub()

    # Relay accumulated steps via WebSocket (non-blocking best-effort)
    if client_id and relay_queue:
        for step in result.reasoning_chain:
            await manager.send_personal_message({
                "type": "REASONING_STEP",
                "payload": {
                    "id": step.id,
                    "layer": step.layer.value,
                    "description": step.description,
                    "duration": int(step.duration_ms),
                    "input_tokens": step.input_tokens,
                    "output_tokens": step.output_tokens,
                    "confidence": step.confidence,
                    "timestamp": int(step.timestamp * 1000) if step.timestamp else int(time.time() * 1000),
                },
            }, client_id)

    return _core_result_to_dict(result, task_type_str)

# ---------------------------------------------------------------------------
# Redis persistence helpers
# ---------------------------------------------------------------------------

async def load_task_history_from_redis():
    global task_history
    try:
        keys = await redis_state_manager.keys(f"{TASK_HISTORY_KEY}:*")
        if keys:
            tasks = []
            for key in keys[:MAX_TASK_HISTORY]:
                task = await redis_state_manager.get(key)
                if task:
                    tasks.append(task)
            task_history = sorted(
                tasks,
                key=lambda x: x.get("performance", {}).get("total_duration", 0),
                reverse=True,
            )
            print(f"[Redis] Loaded {len(task_history)} tasks from history")
    except Exception as e:
        print(f"[Redis] Failed to load task history: {e}")


async def save_task_to_redis(task: dict):
    try:
        task_key = f"{TASK_HISTORY_KEY}:{task['task_id']}"
        await redis_state_manager.set(task_key, task, expire=REDIS_TASK_EXPIRE)
        all_keys = await redis_state_manager.keys(f"{TASK_HISTORY_KEY}:*")
        if len(all_keys) > MAX_TASK_HISTORY:
            for old_key in all_keys[MAX_TASK_HISTORY:]:
                await redis_state_manager.delete(old_key)
    except Exception as e:
        print(f"[Redis] Failed to save task: {e}")

# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global core

    print("=" * 60)
    print("MoRE v3.0 Backend Server starting (real kernel mode)")
    print("=" * 60)

    # 1. Build and start the real more_core kernel
    settings = _build_core_settings()
    core = MoRECore(settings)
    await core.start()
    print(f"[Kernel] MoRECore started — providers: {[p.name for p in settings.providers]}")
    print(f"[Kernel] Feature gates: symbolic={settings.enable_symbolic}, "
          f"evolution={settings.enable_evolution}, metacognition={settings.enable_metacognition}")

    # 2. Connect Redis
    if await redis_state_manager.connect():
        print(f"[Redis] Connected")
        await load_task_history_from_redis()
    else:
        print("[Redis] Connection failed, running without persistence")

    # 3. LLM health check
    try:
        llm_status = await core.llm.health()
        print(f"[LLM] Provider health: {llm_status}")
    except Exception as e:
        print(f"[LLM] Health check error: {e}")

    # 4. Enable RBAC if configured
    if os.getenv("MORE_ENABLE_RBAC", "0") == "1":
        core.rbac.enable()
        core.rbac.assign_role("admin", "admin")
        print("[RBAC] Enforcement enabled")

    yield

    # Shutdown
    await core.stop()
    await redis_state_manager.disconnect()
    print("MoRE v3.0 Backend Server shut down.")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# API key authentication for BFF
# ---------------------------------------------------------------------------

async def _require_bff_api_key(
    authorization: str | None = Header(None, alias="Authorization"),
) -> None:
    """Reject requests when BFF_API_KEY is set and token is wrong."""
    expected = os.getenv("BFF_API_KEY", "")
    if not expected:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    if not hmac.compare_digest(authorization[7:], expected):
        raise HTTPException(status_code=403, detail="Invalid API key")


# ---------------------------------------------------------------------------
# RBAC middleware — enforces role-based access on write endpoints
# ---------------------------------------------------------------------------

WRITE_PATHS = {
    "/api/v1/tasks/execute", "/api/v1/tasks/execute/stream",
    "/api/v1/redis/clear",
}

async def _extract_user_from_token(authorization: str | None) -> str:
    """Derive a user_id from the Bearer token for RBAC lookup.

    In production this would decode a JWT; here we fall back to
    the API-key env var mapping so that dev/test keep working.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return "anonymous"
    token = authorization[7:]
    bff_key = os.getenv("BFF_API_KEY", "")
    if bff_key and hmac.compare_digest(token, bff_key):
        return "admin"
    return "anonymous"


class RBACMiddleware(BaseHTTPMiddleware):
    """Lightweight RBAC gate for write endpoints.

    Controlled via ``MORE_ENABLE_RBAC=1`` env var.
    When disabled (default) all requests pass through.
    """

    async def dispatch(self, request: Request, call_next):
        if os.getenv("MORE_ENABLE_RBAC", "0") != "1":
            return await call_next(request)

        # Only gate write operations
        if request.url.path not in WRITE_PATHS and not request.url.path.startswith("/api/v1/projects/outputs/"):
            return await call_next(request)

        user_id = await _extract_user_from_token(
            request.headers.get("Authorization")
        )

        if user_id == "anonymous":
            return JSONResponse(
                status_code=403,
                content={"error": "RBAC: authentication required for write operations"},
            )

        return await call_next(request)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="MoRE v3.0 Backend API",
    description="Real kernel-powered backend for MoRE v3.0 neuro-symbolic metacognitive architecture",
    version="3.0.0",
    lifespan=lifespan,
)

# CORS — restricted to frontend origins (no wildcard)
_raw_origins = os.getenv(
    "BFF_CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3002,http://127.0.0.1:3002",
)
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins or ["http://localhost:3002"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

# RBAC middleware (disabled by default, enable with MORE_ENABLE_RBAC=1)
app.add_middleware(RBACMiddleware)

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/v1/health")
async def health_check():
    return {
        "status": "healthy",
        "message": "MoRE v3.0 Backend is running (real kernel)",
        "version": "3.0.0",
        "kernel": "more_core",
        "redis_connected": redis_state_manager.is_connected(),
        "providers": core.llm.list_providers() if core else [],
    }


@app.post("/api/v1/tasks/execute", dependencies=[Depends(_require_bff_api_key)])
async def execute_task(request: TaskRequest):
    result = await execute_task_real(request)

    task_history.insert(0, result)
    if len(task_history) > MAX_TASK_HISTORY:
        task_history.pop()

    await save_task_to_redis(result)
    
    # 自动将任务结果转换为产出物（success/partial 状态）
    if result.get("status") in ("success", "partial"):
        await _auto_create_output(result)
    
    return result


@app.post("/api/v1/tasks/execute/stream", dependencies=[Depends(_require_bff_api_key)])
async def execute_task_stream(request: TaskRequest):
    async def generate():
        yield f"data: {json.dumps({'type': 'START', 'task_id': 'pending'})}\n\n"

        try:
            result = await execute_task_real(request)

            # Replay reasoning steps as SSE events
            for step in result.get("reasoning_chain", []):
                yield f"data: {json.dumps({'type': 'LAYER_COMPLETE', 'layer': step['layer'], 'step': step})}\n\n"

            yield f"data: {json.dumps({'type': 'COMPLETE', 'output': result.get('output', '')})}\n\n"

            task_history.insert(0, result)
            await save_task_to_redis(result)

            # 自动将流式任务结果转换为产出物
            if result.get("status") in ("success", "partial"):
                await _auto_create_output(result)
        except Exception as e:
            yield f"data: {json.dumps({'type': 'ERROR', 'message': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/api/v1/tasks/history")
async def get_task_history(limit: int = 20):
    return {"tasks": task_history[:limit], "total": len(task_history)}


@app.get("/api/v1/tasks/types")
async def get_task_types():
    if core:
        # Use real router to determine layers for each type
        from more_core.core.types import TaskRequest as CR
        types_list = []
        for type_str, label in TASK_TYPE_LABELS.items():
            try:
                decision = core.router.route(CR(type=TaskType(type_str), query="probe"))
                layers = [l.value for l in decision.pipeline]
            except Exception:
                layers = ["L0"]
            types_list.append({"id": type_str, "label": label, "layers": layers})
        return {"types": types_list}

    return {"types": [{"id": k, "label": v, "layers": ["L0"]} for k, v in TASK_TYPE_LABELS.items()]}


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    try:
        await manager.send_personal_message({
            "type": "CONNECTED",
            "message": "Connected to MoRE v3.0 Backend (real kernel)",
            "client_id": client_id,
            "redis_connected": redis_state_manager.is_connected(),
        }, client_id)

        while True:
            data = await websocket.receive_json()
            message_type = data.get("type")

            if message_type == "EXECUTE_TASK":
                payload = data.get("payload", {})
                req = TaskRequest(
                    type=payload.get("type", "nlp_task"),
                    query=payload.get("query", ""),
                    context=payload.get("context"),
                    require_metacognitive_monitoring=payload.get("require_metacognitive_monitoring", False),
                    allow_self_improvement=payload.get("allow_self_improvement", False),
                )
                result = await execute_task_real(req, client_id=client_id)

                await manager.send_personal_message({
                    "type": "TASK_COMPLETE",
                    "payload": result,
                }, client_id)

                task_history.insert(0, result)
                await save_task_to_redis(result)

            elif message_type == "PING":
                await manager.send_personal_message({
                    "type": "PONG",
                    "timestamp": int(time.time() * 1000),
                }, client_id)

    except WebSocketDisconnect:
        manager.disconnect(client_id)


@app.get("/api/v1/config/providers")
async def get_configured_providers():
    if not core:
        return {"providers": {}}
    providers_info = {}
    for p in core.settings.providers:
        providers_info[p.name] = {
            "provider": p.provider,
            "model": p.model,
            "endpoint": p.endpoint,
            "configured": True,
        }
    return {"providers": providers_info}


@app.get("/api/v1/llm/status")
async def get_llm_status():
    llm_health = {}
    if core:
        try:
            llm_health = await core.llm.health()
        except Exception:
            llm_health = {"error": "health check failed"}

    return {
        "llm": llm_health,
        "redis": {
            "connected": redis_state_manager.is_connected(),
            "host": os.getenv("REDIS_HOST", "localhost"),
            "port": int(os.getenv("REDIS_PORT", "6379")),
        },
    }


@app.get("/api/v1/system/state")
async def get_system_state():
    if not core:
        return {"status": "starting"}

    return {
        "status": "running",
        "kernel": "more_core",
        "active_layers": [l.value for l in LayerId],
        "providers": core.llm.list_providers(),
        "feature_gates": {
            "symbolic": core.settings.enable_symbolic,
            "evolution": core.settings.enable_evolution,
            "metacognition": core.settings.enable_metacognition,
        },
        "registry": core.registry.stats(),
        "evolution": core.evolution_archive.stats(),
        "memory": core.memory.stats(),
        "active_plugins": [md.name for md in core.plugins.active()],
        "active_tasks": len(task_history),
        "version": "3.0.0",
        "redis_connected": redis_state_manager.is_connected(),
    }


@app.post("/api/v1/redis/clear", dependencies=[Depends(_require_bff_api_key)])
async def clear_redis_history():
    try:
        keys = await redis_state_manager.keys(f"{TASK_HISTORY_KEY}:*")
        for key in keys:
            await redis_state_manager.delete(key)
        return {"status": "success", "message": f"Cleared {len(keys)} tasks"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Project Outputs API (产出物管理)
# ---------------------------------------------------------------------------

PROJECT_OUTPUTS_KEY = "more:v3:project_outputs"


async def _auto_create_output(task_result: dict) -> None:
    """将成功的任务自动转换为产出物并持久化到文件系统"""
    try:
        task_id = task_result.get("task_id", "")
        metadata = task_result.get("metadata", {})
        task_type = metadata.get("task_type", "unknown")
        
        # 提取生成的文件信息
        files = []
        output_text = task_result.get("output", "")
        
        # 解析代码文件
        if "```" in output_text:
            import re
            code_blocks = re.findall(r'```(?:\w+)?\n(.*?)```', output_text, re.DOTALL)
            for idx, code in enumerate(code_blocks):
                lang = "python" if ("def " in code or "class " in code or "import " in code) else "typescript"
                files.append({
                    "path": f"generated/{task_type}/file_{idx + 1}.{lang}",
                    "type": lang,
                    "lines": len(code.strip().split('\n'))
                })
        
        # 解析文档
        docs = []
        if "# " in output_text or "## " in output_text:
            docs.append({
                "path": f"generated/{task_type}/README.md",
                "type": "markdown"
            })
        
        # 生成产出物对象
        output = {
            "id": f"out_{task_id}",
            "name": f"{metadata.get('task_label', task_type)}-{task_id[:8]}",
            "type": task_type,
            "status": task_result.get("status", "completed"),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "files": files,
            "tests": [],
            "docs": docs,
            "metadata": {
                "task_id": task_id,
                "performance": task_result.get("performance", {}),
                "layers": [step.get("layer", "") for step in task_result.get("reasoning_chain", [])],
                "output_preview": output_text[:500] if output_text else ""
            }
        }
        
        # 存储到Redis
        output_key = f"{PROJECT_OUTPUTS_KEY}:{output['id']}"
        await redis_state_manager.set(output_key, output, expire=REDIS_TASK_EXPIRE)
        
        # 持久化到文件系统
        _persist_output_to_disk(output, output_text)
        
        print(f"[Outputs] Created output: {output['id']}")
        
    except Exception as e:
        print(f"[Outputs] Auto-create failed: {e}")


def _persist_output_to_disk(output: dict, output_text: str) -> None:
    """将产出物写入本地文件系统 (outputs/ 目录)。"""
    import os as _os
    task_type = output.get("type", "unknown")
    output_id = output.get("id", "unknown")
    output_dir = f"outputs/{task_type}/{output_id}"
    _os.makedirs(output_dir, exist_ok=True)
    
    # 写入完整输出
    full_path = f"{output_dir}/output.md"
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(f"# {output.get('name', 'Untitled')}\n\n")
        f.write(f"**Type**: {task_type}\n")
        f.write(f"**Created**: {output.get('created_at', '')}\n")
        f.write(f"**Status**: {output.get('status', '')}\n\n")
        f.write("---\n\n")
        f.write(output_text)
        f.write("\n\n---\n")
        f.write(f"\n*MoRE OS Auto-generated Output — {output_id}*")
    
    # 写入元数据
    import json
    meta_path = f"{output_dir}/metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({
            "id": output["id"],
            "name": output["name"],
            "type": task_type,
            "files": output.get("files", []),
            "docs": output.get("docs", []),
            "metadata": output.get("metadata", {}),
        }, f, ensure_ascii=False, indent=2, default=str)
    
    # 提取代码文件到独立文件
    for file_info in output.get("files", []):
        if "```" in output_text:
            import re
            code_blocks = re.findall(r'```(?:\w+)?\n(.*?)```', output_text, re.DOTALL)
            for idx, code in enumerate(code_blocks):
                file_path = f"{output_dir}/file_{idx + 1}.py"
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(code.strip())
    
    print(f"[Outputs] Persisted to disk: {output_dir}")

class ProjectOutput(BaseModel):
    id: str
    name: str
    type: str
    status: str
    created_at: str
    files: list[dict] = []
    tests: list[dict] = []
    docs: list[dict] = []
    metadata: dict = {}


@app.get("/api/v1/projects/outputs")
async def get_project_outputs():
    """获取项目产出物列表"""
    try:
        outputs = []
        seen_ids = set()
        
        # 首先从Redis获取显式创建的产出物
        try:
            output_keys = await redis_state_manager.keys(f"{PROJECT_OUTPUTS_KEY}:*")
            for key in output_keys:
                if ":review" in key:  # 跳过评审记录
                    continue
                stored = await redis_state_manager.get(key)
                if stored and stored.get("id") not in seen_ids:
                    outputs.append(stored)
                    seen_ids.add(stored.get("id"))
        except Exception:
            pass
        
        # 从task_history构建产出物
        for task in task_history[:50]:
            task_id = task.get("task_id", "")
            output_id = f"out_{task_id}"
            
            # 跳过已存在的产出物
            if output_id in seen_ids:
                continue
            
            metadata = task.get("metadata", {})
            task_type = metadata.get("task_type", "unknown")
            task_status = task.get("status", "")
            
            # 提取生成的文件信息
            files = []
            output_text = task.get("output", "")
            
            # 解析代码文件
            if "```" in output_text:
                import re
                code_blocks = re.findall(r'```(?:\w+)?\n(.*?)```', output_text, re.DOTALL)
                for idx, code in enumerate(code_blocks):
                    lang = "python" if ("def " in code or "class " in code or "import " in code) else "typescript"
                    files.append({
                        "path": f"generated/{task_type}/file_{idx + 1}.{lang}",
                        "type": lang,
                        "lines": len(code.strip().split('\n'))
                    })
            
            # 解析文档
            docs = []
            if "# " in output_text or "## " in output_text:
                docs.append({
                    "path": f"generated/{task_type}/README.md",
                    "type": "markdown"
                })
            
            # 生成创建时间戳
            reasoning_chain = task.get("reasoning_chain", [])
            try:
                first_step_ts = reasoning_chain[0].get("timestamp", time.time() * 1000) if reasoning_chain else time.time() * 1000
                created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(first_step_ts / 1000))
            except Exception:
                created_at = time.strftime("%Y-%m-%d %H:%M:%S")
            
            # 对于成功的任务，标记为completed；对于失败的任务，标记为pending_review
            display_status = "completed" if task_status in ("success", "completed", "partial") else "pending_review"
            
            output = {
                "id": output_id,
                "name": f"{metadata.get('task_label', task_type)}-{task_id[:8]}",
                "type": task_type,
                "status": display_status,
                "created_at": created_at,
                "files": files,
                "tests": [],
                "docs": docs,
                "metadata": {
                    "task_id": task_id,
                    "original_status": task_status,
                    "performance": task.get("performance", {}),
                    "layers": [step.get("layer", "") for step in reasoning_chain],
                    "output_preview": output_text[:500] if output_text else "",
                    "output_full": output_text if len(output_text) <= 2000 else output_text[:2000] + "..."
                }
            }
            outputs.append(output)
            seen_ids.add(output_id)
        
        # 按创建时间排序(最新的在前)
        outputs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        
        return {"outputs": outputs, "total": len(outputs)}
    except Exception as e:
        print(f"[Outputs] Error fetching outputs: {e}")
        return {"outputs": [], "total": 0}


@app.get("/api/v1/projects/outputs/{output_id}")
async def get_project_output(output_id: str):
    """获取单个产出物详情"""
    outputs_data = await get_project_outputs()
    for output in outputs_data.get("outputs", []):
        if output.get("id") == output_id:
            return {"output": output}
    raise HTTPException(status_code=404, detail="Output not found")


@app.post("/api/v1/projects/outputs/{output_id}/review")
async def submit_output_review(output_id: str, review: dict):
    """提交产出物评审"""
    try:
        rating = review.get("rating", 0)
        comments = review.get("comments", "")
        approved = review.get("approved", False)
        
        # 保存评审结果
        review_key = f"{PROJECT_OUTPUTS_KEY}:{output_id}:review"
        await redis_state_manager.set(review_key, {
            "output_id": output_id,
            "rating": rating,
            "comments": comments,
            "approved": approved,
            "reviewed_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }, expire=REDIS_TASK_EXPIRE)
        
        return {
            "status": "success",
            "review": {
                "rating": rating,
                "approved": approved,
                "reviewed_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8010, reload=True)
