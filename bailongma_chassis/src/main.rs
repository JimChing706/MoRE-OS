//! BaiLongma Chassis — 最小等效 Rust sidecar 实现（配合 Python 侧 BaiLongmaBridge 5 API 握手联调）。
//!
//! 提供：
//!   * `GET  /health`                       → BridgeStatus.ping() 握手
//!   * `POST /`                              → A2A JSON-RPC 2.0
//!         * `tasks/send`                     → echo/delegate_task (submit)
//!         * `tasks/get`                      → poll_task
//!         * `tasks/cancel`                   → cancel_task
//!
//! 对应 Python 5 API：ping / echo / delegate_task / poll_task / cancel_task
//! 所有响应字段 100% 对齐 `more_core/tests/test_bailongma_chassis_contract.py`
//! 与 `more_core/more_core/a2a/bailongma_bridge.py` 定义的契约。

use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Json};
use axum::routing::{get, post};
use axum::Router;
use serde::Deserialize;
use serde_json::{json, Value};
use uuid::Uuid;

/// 内存任务存储（echo 模式 + delegate 占位，仅用于联调契约验证）。
#[derive(Clone, Default, Debug)]
struct TaskStore {
    tasks: Arc<Mutex<HashMap<String, Value>>>,
}

/// A2A JSON-RPC 2.0 请求 envelope。
#[derive(Debug, Deserialize)]
struct JsonRpcRequest {
    #[allow(dead_code)]
    jsonrpc: Option<String>,
    #[allow(dead_code)]
    id: Option<Value>,
    method: String,
    #[serde(default)]
    params: Value,
}

/// JSON-RPC 统一响应。
fn rpc_ok(result: Value) -> Value {
    json!({ "jsonrpc": "2.0", "id": "", "result": result })
}

fn rpc_err(code: i64, message: impl Into<String>) -> Value {
    json!({ "jsonrpc": "2.0", "id": "", "error": { "code": code, "message": message.into() } })
}

/// 从 params.task.messages[0].content 抽取字段（完全对齐 Python 侧 A2AClient/A2AServer 契约）。
fn first_message(params: &Value) -> Option<(Value, Value)> {
    let task = params.get("task")?;
    let messages = task.get("messages")?.as_array()?;
    let first = messages.first()?;
    let content = first.get("content").cloned().unwrap_or(json!({}));
    let meta = first.get("metadata").cloned().unwrap_or(json!({}));
    Some((content, meta))
}

/// `tasks/send`：
///   * 若 message metadata.mode == "echo" 或 content._qnm_echo == true → echo 同步回包
///   * 否则 → 写入 store 并回 taskId + state
async fn handle_tasks_send(store: &TaskStore, params: Value) -> Value {
    let Some((content, meta)) = first_message(&params) else {
        return rpc_err(-32602, "missing params.task.messages[0]");
    };
    let task_id = Uuid::new_v4().to_string();
    let is_echo = meta
        .get("mode")
        .and_then(|v| v.as_str())
        .map(|s| s == "echo")
        .unwrap_or(false)
        || content
            .get("_qnm_echo")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);

    let state = if is_echo { "completed" } else { "working" };

    let echoed_text = content.get("text").cloned().unwrap_or(json!(""));
    let messages = if is_echo {
        json!([{
            "messageId": Uuid::new_v4().to_string(),
            "role": "agent",
            "parts": [{ "type": "text", "text": echoed_text }],
        }])
    } else {
        json!([])
    };

    // 保存到 store 供 tasks/get 拉取（delegate 场景 200ms 后自动置 completed，模拟处理耗时）
    let entry = json!({
        "taskId": task_id,
        "status": { "state": state },
        "messages": messages.clone(),
    });
    if let Ok(mut g) = store.tasks.lock() {
        g.insert(task_id.clone(), entry);
    }
    if !is_echo {
        // 后台模拟 delegate 处理完成（200ms 后置 completed 并补一条 agent 消息）
        let store2 = store.clone();
        let tid = task_id.clone();
        let pseudo_output = content.get("text").cloned().unwrap_or(json!(""));
        tokio::spawn(async move {
            tokio::time::sleep(tokio::time::Duration::from_millis(200)).await;
            if let Ok(mut g) = store2.tasks.lock() {
                if let Some(v) = g.get_mut(&tid) {
                    v["status"]["state"] = json!("completed");
                    v["messages"] = json!([{
                        "messageId": Uuid::new_v4().to_string(),
                        "role": "agent",
                        "parts": [{ "type": "text", "text": format!("chassis delegate 完成: {}", pseudo_output.as_str().unwrap_or("")) }],
                    }]);
                }
            }
        });
    }

    rpc_ok(json!({
        "taskId": task_id,
        "status": { "state": state },
        "messages": messages,
    }))
}

/// `tasks/get`：按 taskId 返回任务。
async fn handle_tasks_get(store: &TaskStore, params: Value) -> Value {
    let task_id = match params.get("taskId").or_else(|| params.get("task_id")).and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return rpc_err(-32602, "Task not found"),
    };
    let locked = store.tasks.lock().ok();
    let entry = locked.as_ref().and_then(|g| g.get(&task_id)).cloned();
    match entry {
        Some(e) => rpc_ok(e),
        None => rpc_err(-32602, "Task not found"),
    }
}

/// `tasks/cancel`：回 true（模拟成功取消）。
async fn handle_tasks_cancel(store: &TaskStore, params: Value) -> Value {
    let task_id = match params.get("taskId").or_else(|| params.get("task_id")).and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return rpc_err(-32602, "Task not found"),
    };
    let removed = if let Ok(mut g) = store.tasks.lock() {
        g.remove(task_id).is_some()
    } else {
        false
    };
    rpc_ok(json!({ "canceled": removed }))
}

/// A2A JSON-RPC dispatcher。
async fn rpc_handler(State(store): State<TaskStore>, Json(req): Json<JsonRpcRequest>) -> impl IntoResponse {
    let result = match req.method.as_str() {
        "tasks/send" => handle_tasks_send(&store, req.params).await,
        "tasks/get" => handle_tasks_get(&store, req.params).await,
        "tasks/cancel" => handle_tasks_cancel(&store, req.params).await,
        other => rpc_err(-32601, format!("Method not found: {}", other)),
    };
    (StatusCode::OK, Json(result))
}

/// GET /health：chassis 握手（完全对齐 BaiLongmaBridge.ping 契约 2xx → reachable=true）。
async fn health_handler() -> impl IntoResponse {
    (
        StatusCode::OK,
        Json(json!({
            "service": "bailongma-chassis",
            "version": env!("CARGO_PKG_VERSION"),
            "ok": true,
            "features": ["a2a", "echo", "delegate_v1"],
        })),
    )
}

#[tokio::main]
async fn main() {
    std::env::set_var("RUST_LOG", "info");
    tracing_subscriber::fmt().try_init().ok();

    let store = TaskStore::default();
    let app = Router::new()
        .route("/health", get(health_handler))
        .route("/", post(rpc_handler))
        .with_state(store);

    let port: u16 = std::env::var("BAILONGMA_PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(9988);
    let addr = std::net::SocketAddr::from(([127, 0, 0, 1], port));
    tracing::info!(%addr, "BaiLongma chassis 起服");
    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
