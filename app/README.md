# QNMing MoRE OS — Dashboard

> **平台内核位置**: 所有平台化的 L0–L5 内核、插件系统、LLM 抽象、沙箱、
> 治理/进化/元认知子系统都集中在仓库根目录的 `more_core/` Python 包中。
> 本 `app/` 目录仅保留用于演示的 **前端控制台** (React + TypeScript)，
> 它通过 `more-os` 暴露的 `POST /api/v1/tasks/execute` 等平台中立 API
> 对接内核，不再包含任何行业特定（麻将 / 娱乐）脚本。
>
> 启动内核： `pip install -e more_core[api] && more-os serve --port 8001`

## 工程化落地方案

### 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    MoRE v3.0 Agent OS                        │
│              管理控制台 (React + TypeScript)                  │
├─────────────────────────────────────────────────────────────┤
│  L5 元认知层 │ L4 认知层 │ L3 符号推理层 │ L2 神经进化层      │
│  HyperAgents │ 任务理解  │ NSPA-AI      │ DGM引擎           │
│  校准器      │ 资源分配  │ 本体引擎      │ 归档管理器         │
│  策略选择器   │ 规划引擎  │ 规则引擎      │ 探索引擎          │
├─────────────────────────────────────────────────────────────┤
│  L1 协作编排层              │ L0 执行层                      │
│  OMAC优化器 │ MARL训练器    │ 工具执行器 │ 代码解释器 │ API网关 │
│  动态路由器  │               │           │           │        │
├─────────────────────────────────────────────────────────────┤
│  支撑系统: 记忆系统 │ 本体引擎 │ 进化归档 │ 安全治理 │ 监控反馈 │
└─────────────────────────────────────────────────────────────┘
```

### 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| 前端框架 | React 19 + TypeScript | UI组件 |
| 构建工具 | Vite 7 | 打包构建 |
| 样式 | Tailwind CSS 3.4 + shadcn/ui | UI样式 |
| 路由 | React Router 7 | 页面路由 |
| 容器 | Docker + Nginx | 部署 |
| 监控 | Prometheus + Grafana | 可观测性 |
| 缓存 | Redis 7 | 状态缓存 |

### 快速开始

#### 1. 本地开发

```bash
# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 构建生产版本
npm run build

# 预览生产构建
npm run preview
```

#### 2. Docker 部署

```bash
# 构建并启动全部服务
docker-compose up -d

# 查看日志
docker-compose logs -f more-console

# 停止服务
docker-compose down
```

#### 3. 访问服务

| 服务 | 地址 | 说明 |
|------|------|------|
| 管理控制台 | http://localhost:3080 | QNMing MoRE OS — Dashboard BFF Server |
| Prometheus | http://localhost:9090 | 监控指标 |
| Grafana | http://localhost:3001 | 可视化面板 (admin/morev3admin) |

### 项目结构

```
├── src/
│   ├── types/
│   │   └── morev3.ts              # 核心类型定义
│   ├── core/
│   │   └── moreEngine.ts          # 模拟引擎系统
│   ├── components/
│   │   ├── LayerVisualizer.tsx    # 六层架构可视化
│   │   ├── SystemDashboard.tsx    # 系统状态仪表盘
│   │   ├── TaskPanel.tsx          # 任务执行面板
│   │   ├── EvolutionBrowser.tsx   # DGM进化归档浏览器
│   │   ├── SafetyPanel.tsx        # 安全治理面板
│   │   └── MemoryPanel.tsx        # 记忆系统面板
│   ├── pages/
│   │   └── Home.tsx               # 主控制台页面
│   ├── App.tsx                    # 根组件
│   └── main.tsx                   # 入口文件
├── monitoring/
│   └── prometheus.yml             # Prometheus配置
├── Dockerfile                     # 容器构建
├── docker-compose.yml             # 编排配置
├── nginx.conf                     # Nginx配置
└── README.md                      # 本文件
```

### 六层架构详解

#### L5: 元认知层 (Metacognition)
- **HyperAgent引擎**: 集成Meta FAIR 2026年研究成果，实现元认知自修改
- **校准器**: 置信度-准确度对齐监控，参考Mirror基准
- **策略选择器**: 基于任务难度选择最优推理策略

#### L4: 认知层 (Cognition)
- **任务解析器**: 深度语义理解
- **资源分配器**: 计算资源动态分配
- **规划引擎**: 长程规划与子任务分解

#### L3: 符号推理层 (Symbolic Reasoning)
- **本体引擎**: AOW标准 + 领域本体（角色/交互/治理三层）
- **NSPA-AI集成器**: 神经符号融合推理
- **规则引擎**: 基于本体的约束检查

#### L2: 神经进化层 (Neural-Evolution)
- **DGM引擎**: 达尔文进化机制，SWE-bench 20%→50%
- **归档管理器**: Agent版本树管理
- **探索引擎**: 开放域探索，stepping stone发现

#### L1: 协作编排层 (Orchestration)
- **OMAC优化器**: 五维协作优化框架
- **MARL训练器**: 多Agent强化学习
- **动态路由器**: 难度感知自适应路由

#### L0: 执行层 (Execution)
- **工具执行器**: 安全沙箱工具调用
- **代码解释器**: Python/Shell执行
- **API网关**: 外部服务接口

### 核心功能

1. **六层架构实时可视化** — 观察数据流在各层间的流动
2. **系统状态监控** — 吞吐量、延迟、错误率、引擎负载
3. **任务执行面板** — 8种任务类型的快速执行与推理链可视化
4. **DGM进化归档浏览器** — Agent进化谱系、分支管理、收敛状态
5. **安全治理中心** — AOW本体约束、安全事件分级处理
6. **记忆系统可视化** — 情景/语义/程序记忆的管理与查询

### API 接口 (模拟)

```typescript
// 执行任务
POST /api/v1/tasks/execute
Body: { type: TaskType, query: string, options?: TaskOptions }
Response: TaskResult

// 获取系统状态
GET /api/v1/system/status
Response: SystemState

// 获取进化归档
GET /api/v1/evolution/archive
Response: EvolutionArchive

// 获取安全事件
GET /api/v1/safety/events
Response: SafetyEvent[]

// 获取记忆
GET /api/v1/memory/{type}
Response: MemoryEntry[]
```

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `80` | 服务端口 |
| `API_BASE_URL` | `/api/v1` | API基础路径 |
| `SIMULATION_INTERVAL` | `3000` | 模拟刷新间隔(ms) |
| `ENABLE_METACOGNITION` | `true` | 启用元认知层 |
| `ENABLE_EVOLUTION` | `true` | 启用进化层 |
| `SAFETY_LEVEL` | `strict` | 安全级别 |

### 版本历史

| 版本 | 时间 | 核心特性 |
|------|------|---------|
| v1.0 | 2024 | Meta-Agent OS 六层抽象架构 |
| v2.0 | 2025 | MoRE 四项理论融合 |
| **v3.0** | **2026** | **神经符号元认知混合架构** |

---

**MoRE v3.0** — *不止于解决问题，持续改进解决问题的方式*
