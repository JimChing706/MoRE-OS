# Mahjong Industry Pack

> QNMing MoRE OS 插件个案 — 麻将策略 AI

## 概述

本插件将原 `MAHJONG_PROJECT_Another_one/` 项目降级为 QNMing MoRE OS 的一个 **Industry Pack** 插件个案，演示如何将领域特定应用（棋牌 AI）接入 MoRE OS 内核。

## 文件结构

```text
mahjong-industry-pack/
├── plugin.json             # 插件清单
├── main.py                 # 插件入口（PluginBase 子类）
├── README.md               # 本文件
└── legacy/                 # 原始项目文件（迁移自 MAHJONG_PROJECT_Another_one/）
    ├── mahjong_rules.py    # 麻将规则引擎
    ├── ai_agent.py         # AI 策略 Agent
    ├── game_manager.py     # 游戏会话管理
    ├── multiplayer_server.py # WebSocket 多人服务器
    ├── mahjong-core/       # Rust/WASM 麻将核心
    └── ...                 # 其他迁移文件
```

## 状态

- **当前**: 插件骨架已创建，`main.py` 提供 `Plugin` 入口类
- **待办**: 将 `legacy/` 中的模块逐步适配为 MoRE OS 工具注册和层集成

## 安装

```bash
# 在 MoRE OS 根目录
pip install -e more_core/
# 将本插件目录配置到 MoRE OS 插件搜索路径
export MORE_PLUGIN_PATH=plugins/mahjong-industry-pack
```
