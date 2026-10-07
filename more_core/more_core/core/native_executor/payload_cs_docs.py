"""CS shooter 交付物静态内容（SRS / 规划大纲 / 实施细则 / 技术方案 / 前端入口）。

独立成模块，避免 payload_mixins.py 因长文档字符串而难以维护。
内容由 deliverables/cs_fps 下的真实交付文档生成，与工程骨架一并写入项目根目录，
供 requirement_verifier 做 REQ 覆盖度核验。
"""

CS_SRS_DOC = """
# 软件需求规格说明书（SRS）
## CS 风格第一人称射击游戏 — Rust 核心 + 现代前端渲染

版本：1.0.0 ｜ 作者：qnming ｜ 日期：2026-10-07

---

## 1. 引言

### 1.1 目的
本文档定义「Rust + 前端最新技术开发 CS（Counter-Strike）风格第一人称射击游戏」的完整软件需求，作为设计、实现、测试与验收的基准。所有需求可度量、可追溯。

### 1.2 范围
- 范围内：第一人称移动与视角、射击与命中判定、T/CT 阵营对抗、回合制对局、经济系统、武器体系、地图与碰撞、网络同步、计分板、可运行的工程骨架。
- 范围外（后续迭代）：反作弊、皮肤/饰品交易、匹配天梯、录像回放。

### 1.3 术语与缩略语
| 术语 | 含义 |
|------|------|
| FPS | First-Person Shooter，第一人称射击 |
| T / CT | Terrorist 恐怖分子 / Counter-Terrorist 反恐精英 |
| tick | 服务端逻辑帧，目标 64 tick/s |
| RTT | 网络往返延迟 |
| ITD | Import Task Document，任务导入文档 |
| WASM | WebAssembly |

### 1.4 参考
- QNMing MoRE OS 平台源码（more_core/core/import_task.py、api/routers/import_task.py）
- 本任务 ITD 文档（itd-cs-fps.md）

---

## 2. 总体描述

### 2.1 产品定位
一款浏览器可运行、局域网可对战的 CS 风格 FPS：Rust 提供高性能、内存安全、确定性可测的游戏核心；前端提供 3D 渲染与交互。

### 2.2 目标用户
- 开发/演示用途的技术验证用户；
- 局域网内的休闲竞技玩家。

### 2.3 运行环境
| 项 | 要求 |
|----|------|
| 核心 | Rust stable（edition 2021+），std-only 可离线构建 |
| 前端 | 支持 WebGL2 的现代浏览器；优先 WebGPU |
| 服务 | 本机 / 局域网（UDP 或 WebSocket） |

### 2.4 设计约束
- 核心逻辑确定性（同输入 → 同输出），无 GC 停顿；
- 骨架阶段依赖最小化，保证离线编译；
- 前后端通过明确的接口约定解耦。

---

## 3. 功能需求

### FR-1 移动与视角
- FR-1.1 支持 WASD 前后左右移动，移动速度 8 m/s，匀速、无加速滑步。
- FR-1.2 鼠标环视（指针锁定），水平 360° 无限制，俯仰限制 ±85°。
- FR-1.3 移动与碰撞：玩家无法进入实体体素，位置钳制在地图边界内。

### FR-2 射击与命中判定
- FR-2.1 按下开火键触发射击，武器按射速节流。
- FR-2.2 命中判定为服务端权威：基于视线与距离的确定性判定（骨架阶段为距离/可见性判定，后续升级为射线）。
- FR-2.3 爆头倍率、护甲减伤参与伤害结算。

### FR-3 阵营与回合
- FR-3.1 每局分为 T 与 CT 两阵营，玩家加入时分配。
- FR-3.2 回合制：一方全灭或目标达成（安装/拆除炸弹，后续迭代）判定回合结束。
- FR-3.3 回合结束进入结算与下一回合倒计时。

### FR-4 经济系统
- FR-4.1 击杀、回合胜负、埋包/拆包产生金钱奖励。
- FR-4.2 玩家在回合起始购买武器与装备。

### FR-5 武器体系
- FR-5.1 至少 5 类武器：匕首、手枪、冲锋枪、步枪、狙击枪。
- FR-5.2 每类武器含伤害、爆头倍率、射速、价格属性。
- FR-5.3 支持切换武器。

### FR-6 地图与碰撞
- FR-6.1 地图由世界边界 + 实体体素（AABB）构成。
- FR-6.2 提供 T/CT 双方出生点。

### FR-7 网络同步
- FR-7.1 服务端广播快照（tick、玩家位置、朝向）。
- FR-7.2 客户端上行移动/射击消息。
- FR-7.3 消息类型：JOIN、MOVE、SHOT、SNAPSHOT。

### FR-8 计分与观战
- FR-8.1 显示双方存活、比分、经济。
- FR-8.2 死亡后可进入旁观视角（后续迭代）。

---

## 4. 非功能需求

### NFR-1 性能
- 客户端渲染 ≥ 60 FPS（1080p）。
- 服务端 tick 64 Hz，单帧逻辑开销 < 1 ms（核心逻辑，不含 IO）。
- 客户端输入到画面响应 < 100 ms。

### NFR-2 网络
- 局域网 RTT 目标 < 20 ms；延迟补偿在骨架阶段预留接口。

### NFR-3 安全
- 服务端权威：客户端只发送输入意图，不信任客户端命中判定。
- 消息长度与频率限制，防洪泛。

### NFR-4 可维护性
- 核心模块单元测试覆盖（骨架阶段 ≥ 8 用例）。
- cargo build / test / clippy 全绿；前端 node --check 通过。

### NFR-5 兼容性
- 前端在无 WebGPU 时自动回退 WebGL。

---

## 5. 接口需求

### 5.1 Rust 核心对外接口
| 接口 | 说明 |
|------|------|
| `math::Vec3` | 三维向量与运算 |
| `player::Player` | 玩家状态机（移动/受伤/死亡） |
| `weapon::weapon_table` | 武器数据表 |
| `world::World` | 地图边界与碰撞 |
| `net::NetMessage` | 网络消息编解码 |

### 5.2 前端 ↔ 核心
- 前端预留 `window.__csBridge` 通信接口，后续替换为 WASM 直接调用。
- 消息采用文本行协议（tag + 空格分隔参数），便于调试与扩展。

---

## 6. 验收标准
1. 4 份文档（SRS / 规划大纲 / 实施细则 / 技术方案）落盘。
2. `cargo build` 退出码 0，`cargo test` 全部通过。
3. 前端 `node --check` 通过，页面可加载并支持第一人称移动。
4. ITD 通过平台 parse / validate，导入成功并生成 task_id。

---

## 7. 需求追溯矩阵
| 需求 | 文档章节 | 实现模块 | 测试 |
|------|----------|----------|------|
| FR-1 移动视角 | SRS §3 | player.rs + web/main.js | 移动推进、钳制用例 |
| FR-2 射击命中 | SRS §3 | player.rs（apply_damage） | 击杀/伤害用例 |
| FR-5 武器 | SRS §3 | weapon.rs | 数据表用例 |
| FR-6 地图碰撞 | SRS §3 | world.rs | 体素/出生点用例 |
| FR-7 网络 | SRS §3 | net.rs | 编解码往返用例 |
| NFR-1 性能 | SRS §4 | 确定性 tick 循环 | sim 运行验证 |
"""

CS_PLAN_DOC = """
# 软件开发规划大纲
## CS 风格 FPS（Rust 核心 + 现代前端）

版本：1.0.0 ｜ 日期：2026-10-07

---

## 1. 目标与范围
分阶段交付一款浏览器可运行、局域网可对战的 CS 风格 FPS。Rust 负责游戏核心（数学/玩家/武器/地图/网络消息/确定性 tick），前端负责 3D 渲染与交互，最终通过 WASM 桥接完成前后端融合。

## 2. 里程碑与迭代计划

### M1 — 需求与设计冻结（本次交付）
- 产出：SRS、规划大纲、实施细则、技术方案、ITD 导入。
- 验收：4 份文档齐备，ITD 通过平台 parse/validate。

### M2 — Rust 核心骨架
- 产出：可编译 Rust 工程（math / player / weapon / world / net 五模块）+ 单元测试。
- 验收：`cargo build` 与 `cargo test` 全绿，核心模块用例 ≥ 8。

### M3 — 前端渲染骨架
- 产出：index.html + main.js，第一人称相机 + WASD 移动 + 基础场景。
- 验收：页面可加载，相机与移动可用，`node --check` 通过。

### M4 — 前后端融合与网络
- 产出：WASM 桥接、消息协议接入、局域网房间与快照同步。
- 验收：两台设备可加入同一房间并看到对方移动。

### M5 — 玩法闭环与发布
- 产出：回合/经济/胜负结算、计分板、打包发布（tar.gz / zip + Docker）。
- 验收：一局完整对局可玩，交付物打包 ≥ 200 KB。

## 3. 工作分解结构（WBS）
1. 需求与设计：SRS / 规划 / 细则 / 选型（M1）
2. 核心开发：数学库 → 玩家状态机 → 武器 → 地图 → 网络消息 → tick 循环（M2）
3. 前端开发：场景 → 光照 → 相机控制 → 移动 → HUD（M3）
4. 集成：WASM 编译 → 消息对接 → 快照渲染（M4）
5. 玩法与发布：经济/回合/结算 → 测试 → 打包（M5）

## 4. 工期与资源估算
| 阶段 | 工期 | 人力 | 关键产出 |
|------|------|------|----------|
| M1 | 0.5 天 | 1 | 文档 + ITD |
| M2 | 1 天 | 1 | Rust 核心 + 测试 |
| M3 | 1 天 | 1 | 前端骨架 |
| M4 | 2 天 | 1 | 联机对战 |
| M5 | 1 天 | 1 | 玩法闭环 + 打包 |
| 合计 | 约 5.5 人日 | | |

两条开发线：Rust 核心（M2）与前端（M3）可并行，M4 汇合。

## 5. 风险清单与应对
| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| Rust 引擎选型过重导致编译慢 | 中 | 高 | 骨架阶段 std-only，引擎后置 |
| WebGPU 浏览器兼容性不足 | 中 | 中 | 自动回退 WebGL/Three.js |
| WASM 桥接复杂度高 | 中 | 高 | 先用文本协议通信，WASM 后置 |
| 命中判定/延迟补偿复杂 | 高 | 高 | 骨架用距离判定，预留权威服务端接口 |
| 范围发散 | 中 | 高 | Kill Criteria 冻结 MVP 范围 |

## 6. 迭代节奏
- 每里程碑结束做一次可运行验证 + 文档更新。
- 提交粒度：单模块单提交，附带测试。
"""

CS_IMPL_DOC = """
# 软件开发实施细则
## CS 风格 FPS（Rust 核心 + 现代前端）

版本：1.0.0 ｜ 日期：2026-10-07

---

## 1. 仓库目录结构
```text
cs-fps/
├── Cargo.toml            # 包定义（std-only，无外部依赖）
├── src/
│   ├── lib.rs            # 库入口，导出各模块
│   ├── main.rs           # 可执行入口：确定性仿真（可运行验证）
│   ├── math.rs           # Vec3 / AABB / 距离
│   ├── player.rs         # 玩家状态机
│   ├── weapon.rs         # 武器数据表
│   ├── world.rs          # 地图边界与碰撞
│   └── net.rs            # 网络消息编解码
├── web/
│   ├── index.html        # 页面 + importmap
│   ├── main.js           # 第一人称相机 + WASD + 场景
│   └── package.json      # {"type":"module"}
└── (deliverables/cs_fps/ 下为文档与 ITD)
```

## 2. 编码规范

### Rust
- `cargo fmt` 统一格式；`#![warn(clippy::all)]`。
- 公开 API 写文档注释；模块保持单一职责。
- 核心逻辑确定性：不依赖系统时间、不用浮点哈希（除非显式要求）。
- 错误处理：核心模块返回 `Option`/`Result`，不 `unwrap` 业务路径（测试与常量表除外）。

### JavaScript
- ES Module，不引入构建步骤（骨架阶段）。
- 使用 `const`/`let`，不用 `var`；函数式拆分。
- 关键交互（相机、移动、桥接）写注释说明与 Rust 的对应关系。

## 3. 构建与测试命令
```bash
# Rust
export PATH="/Users/qnming/.cargo/bin:$PATH"
DEVELOPER_DIR=/Library/Developer/CommandLineTools cargo build --offline
DEVELOPER_DIR=/Library/Developer/CommandLineTools cargo test --offline
DEVELOPER_DIR=/Library/Developer/CommandLineTools cargo clippy --offline

# 前端语法校验
node --check web/main.js

# 本地静态预览
cd web && python3 -m http.server 8080
```

## 4. 持续集成（CI）
- 推送前门禁：`cargo build` + `cargo test` + `node --check`，任一失败阻断。
- 提交前本地预检：`cargo fmt --check && cargo clippy && cargo test`。

## 5. 分支与提交规范
- `main` 受保护；功能走 `feat/xxx`，修复走 `fix/xxx`。
- 提交信息：`<type>(<scope>): <subject>`，type ∈ feat/fix/test/docs/refactor/chore。

## 6. 代码评审与质量门禁
| 门禁 | 阈值 |
|------|------|
| cargo build | exit 0 |
| cargo test | 全绿 |
| cargo clippy | 无 warning |
| node --check | exit 0 |
| 核心模块测试用例 | ≥ 8 |

## 7. 发布与打包
- 交付物：源码 tar.gz + zip；前端静态资源 + 可执行产物。
- 服务端容器化：Dockerfile 基于 rust:slim 构建核心，nginx 托管前端。
- 版本号语义化：MAJOR.MINOR.PATCH，当前 0.1.0。
"""

CS_TECH_DOC = """
# 技术方案优选策略与推荐落地方案
## CS 风格 FPS（Rust 核心 + 现代前端）

版本：1.0.0 ｜ 日期：2026-10-07

---

## 1. 选型总览
| 维度 | 候选 | 推荐 |
|------|------|------|
| Rust 引擎/架构 | bevy / wgpu 自研 / 纯逻辑核心 | 纯逻辑核心（骨架），演进到 bevy |
| 前端渲染 | WebGPU / WebGL + Three.js | WebGPU 优先 + Three.js(WebGL) 兜底 |
| 网络 | UDP 权威服务器 / WebSocket | UDP 权威（局域网） |
| 前后端桥接 | WASM / 文本协议 | 文本协议先行，WASM 后置 |

## 2. Rust 引擎选型对比
| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| bevy | 全栈 ECS、渲染/输入/音频齐全、社区活跃 | 编译慢、依赖重、学习曲线、离线构建难 | 中后期采用 |
| wgpu 自研 | 极致控制、跨平台、可编译 WASM | 需要自写渲染/输入/资源管理 | 进阶路线 |
| 纯逻辑核心（std-only） | 秒级编译、确定性可测、离线友好 | 无渲染，需前端承接 | ✅ 骨架阶段 |

**策略**：骨架阶段以纯逻辑核心保证「可编译、可测、可运行」的快速闭环；玩法成熟后引入 bevy 承载渲染与输入，逻辑核心保持独立可复用。

## 3. 前端渲染选型对比
| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| WebGPU | 现代 API、低开销、面向未来 | 浏览器支持未全覆盖 | 首选 |
| WebGL + Three.js | 生态成熟、兼容性最好、开发快 | 较 WebGPU 开销略高 | 兜底 |

**策略**：检测 WebGPU 可用则走 WebGPURenderer，否则回退 WebGLRenderer（Three.js 同 API 切换成本低）。

## 4. 网络选型对比
| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| UDP 权威服务器 | 低延迟、FPS 标配、服务端权威 | 需处理丢包/乱序、NAT | ✅ 局域网首选 |
| WebSocket | 简单、穿透性好、浏览器原生 | 延迟较高、TCP 队头阻塞 | 浏览器直连兜底 |

**策略**：局域网走 UDP 权威；浏览器纯前端联调阶段用 WebSocket 过渡。

## 5. 前后端桥接对比
| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| WASM（wasm-bindgen） | 复用同一套 Rust 核心、零 JS 重写 | 需 wasm 工具链、类型转换成本 | 融合阶段 |
| 文本行协议 | 极简、可调试、无工具链 | 有序列化开销 | ✅ 骨架阶段 |

## 6. 推荐落地方案（唯一）
**「Rust 纯逻辑核心 + Three.js（WebGPU 优先 / WebGL 兜底）+ 文本协议先行 + UDP 权威演进」**

理由：
1. 骨架阶段零外部依赖，离线可编译、秒级验证，风险最低；
2. 核心逻辑确定性、可单测，符合服务端权威的架构要求；
3. 前端用业界成熟 Three.js，WebGPU 可平滑升级，不锁死；
4. 网络分层：协议先行打通信道，再替换为 UDP 权威，避免一步到位的高复杂度。

## 7. 落地步骤
1. 建 Rust std-only 核心（math/player/weapon/world/net）+ 测试；
2. 建前端第一人称骨架（相机 + WASD + 场景）；
3. 文本协议打通「前端上行意图 → 核心 tick → 快照下行」；
4. 引入 wasm-bindgen 编译核心为 WASM，前端直接调用；
5. 引入 UDP 权威服务端 + 房间管理 + 延迟补偿；
6. 玩法闭环（回合/经济/结算）+ 打包发布。

## 8. 回退策略
- WebGPU 不可用 → 回退 WebGL；
- WASM 桥接受阻 → 维持文本协议（HTTP/WebSocket）通信；
- UDP 穿透失败 → 回退 WebSocket 房间中转；
- 引擎引入导致编译/复杂度失控 → 保持纯逻辑核心 + 前端渲染的架构不变。
"""

CS_MAIN_JS = """
import * as THREE from 'three';

const hud = document.getElementById('hud');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0a0e14);
scene.fog = new THREE.Fog(0x0a0e14, 30, 120);

const camera = new THREE.PerspectiveCamera(75, innerWidth / innerHeight, 0.1, 500);
camera.position.set(0, 1.7, 0);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(innerWidth, innerHeight);
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
document.body.appendChild(renderer.domElement);

// lighting
scene.add(new THREE.HemisphereLight(0xbfd8ff, 0x223344, 1.1));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(40, 60, 20);
scene.add(sun);

// ground + placeholder boxes (dust2-like layout)
const ground = new THREE.Mesh(
  new THREE.PlaneGeometry(200, 200),
  new THREE.MeshStandardMaterial({ color: 0x3a4a3a })
);
ground.rotation.x = -Math.PI / 2;
scene.add(ground);

const boxes = [
  { x: 0, z: 0, s: 16, h: 16 },
  { x: -20, z: -20, s: 2, h: 4 },
  { x: 30, z: 15, s: 8, h: 8 },
  { x: -35, z: -30, s: 6, h: 10 },
];
for (const b of boxes) {
  const m = new THREE.Mesh(
    new THREE.BoxGeometry(b.s, b.h, b.s),
    new THREE.MeshStandardMaterial({ color: 0x8a7a5a })
  );
  m.position.set(b.x, b.h / 2, b.z);
  scene.add(m);
}

// first-person controller: pointer lock + WASD
const keys = {};
addEventListener('keydown', (e) => (keys[e.code] = true));
addEventListener('keyup', (e) => (keys[e.code] = false));

let yaw = 0;
let pitch = 0;
let locked = false;
const canvas = renderer.domElement;
canvas.addEventListener('click', () => canvas.requestPointerLock());
document.addEventListener('pointerlockchange', () => {
  locked = document.pointerLockElement === canvas;
});
document.addEventListener('mousemove', (e) => {
  if (!locked) return;
  yaw -= e.movementX * 0.0022;
  pitch -= e.movementY * 0.0022;
  pitch = Math.max(-1.5, Math.min(1.5, pitch));
});

const SPEED = 8; // m/s
let last = performance.now();

function tick(now) {
  const dt = Math.min((now - last) / 1000, 0.05);
  last = now;
  camera.rotation.order = 'YXZ';
  camera.rotation.y = yaw;
  camera.rotation.x = pitch;

  const f = (keys['KeyW'] ? 1 : 0) - (keys['KeyS'] ? 1 : 0);
  const r = (keys['KeyD'] ? 1 : 0) - (keys['KeyA'] ? 1 : 0);
  const forward = new THREE.Vector3(0, 0, -1).applyAxisAngle(new THREE.Vector3(0, 1, 0), yaw);
  const right = new THREE.Vector3(1, 0, 0).applyAxisAngle(new THREE.Vector3(0, 1, 0), yaw);
  const dir = new THREE.Vector3().addScaledVector(forward, f).addScaledVector(right, r);
  if (dir.lengthSq() > 0) dir.normalize().multiplyScalar(SPEED);

  camera.position.addScaledVector(dir, dt);
  camera.position.y = 1.7;

  hud.textContent =
    `pos ${camera.position.x.toFixed(1)}, ${camera.position.z.toFixed(1)} · ` +
    `yaw ${(yaw * 57.3).toFixed(0)}° · ${locked ? '已锁定' : '未锁定'}`;
  renderer.render(scene, camera);
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

// 与 Rust/WASM 核心的通信接口约定（骨架阶段预留，后续替换为 WASM 直接调用）
window.__csBridge = {
  send: (msg) => console.log('[net]', msg),
};
console.log('CS-FPS 前端骨架已启动 · WebGL 渲染 (可升级 WebGPURenderer)');
"""

CS_INDEX_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CS-FPS 前端骨架 — Rust 核心 + WebGPU/WebGL</title>
<style>
  html,body{margin:0;height:100%;overflow:hidden;background:#0a0e14;font-family:system-ui,sans-serif}
  #hud{position:fixed;top:12px;left:16px;color:#9fe;font:13px/1.5 monospace;white-space:pre;pointer-events:none}
  #cross{position:fixed;left:50%;top:50%;width:12px;height:12px;margin:-6px;border:1px solid #4f8;border-radius:50%}
</style>
</head>
<body>
<div id="hud">loading…</div>
<div id="cross"></div>
<script type="importmap">
{ "imports": { "three": "https://unpkg.com/three@0.160.0/build/three.module.js" } }
</script>
<script type="module" src="./main.js"></script>
</body>
</html>
"""
