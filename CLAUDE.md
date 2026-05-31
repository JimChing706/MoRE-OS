1. 写代码前先思考
先说明假设，不要猜。模型不会读心，别指望它能自动知道你的意思。

2. 简单优先
最少代码，不做投机式抽象。一旦你让 Claude 为“未来灵活性”加东西，可能就多出 200 行下季度要删的代码。

3. 外科手术式修改
只改必须改的地方。别让它顺手优化旁边的代码，PR 就是这么膨胀的。

4. 目标驱动执行
先定义成功标准，然后循环直到验证通过。没有成功标准，Claude 要么无限循环，要么过早停止。

5. 只把模型用于判断型任务
比如分类、草稿、总结、抽取。不要让模型处理路由、重试、状态码处理、确定性转换。代码能回答的，就让代码回答。

6. Token 预算不是建议
单任务 4000，单会话 30000。长时间调试到第 40 条消息时，Claude 会重新建议你第 5 条消息已经否掉的修复方案。

7. 暴露冲突，不要折中平均
代码库里有两种模式？选一种。Claude 把两种混在一起，错误就会被吞两次。

8. 先读再写
先读 exports、调用方、共享工具。Claude 很可能在一个已有相同函数旁边，再加一个重复函数，只因为它没读到。

9. 测试要验证意图，而不只是行为
如果业务逻辑变了测试却不会失败，这个测试就是错的。Claude 写的 12 个测试都可能通过，即使函数实际只返回一个常量。

10. 每个重要步骤都要 checkpoint
Claude 可能在第 4 步已经坏掉的状态上继续完成第 5、6 步，而没人发现，浪费一小时。

11. 匹配代码库约定
项目用 class components，就不要默默改成 hooks。测试模式可能依赖 `componentDidMount`，hooks 会破坏它，却不一定暴露问题。

12. 失败要大声暴露
“成功完成”，但 14% 的记录被静默跳过，这是最糟糕的一类 bug。要暴露不确定性，不要藏起来。

真正会复利增长的，不是下一个框架，而是：

- 把 `CLAUDE.md` 当作跨会话的组织记忆
- 基于 eval 改进，而不是凭感觉改
- 重视 checkpoint，而不是一味追求速度
- 明确暴露冲突，而不是静默混合
- 纪律永远比框架重要
- 一个仓库，一个规则文件，没有例外

## 项目上下文 (2026-05-22)

- **版本**: v0.5.1
- **运行环境**: Python 3.14, `.venv/`, macOS
- **API 端口**: 8010 (当前活跃)
- **LLM Provider**: Ollama `qwen2.5:7b` (primary) + LM Studio (fallback)
- **dotenv**: `more_core/.env` 自动加载
- **前端**: `app/` React + Vite, 端口 3002/3003

### 已知问题
- 扫雷 GUI (8080) 端口被系统占用，不影响核心
- LM Studio 大模型响应慢 (~30s)，生产用 Ollama
- `minesweeper_game` 依赖 `minesweeper_agent`，关闭顺序需反向依赖解析

### 关键模块
- `more_core/more_core/runtime/orchestrator.py` — 核心编排器
- `more_core/more_core/api/routers/` — 18 个路由模块
- `more_core/more_core/llm/manager.py` — LLM 多 Provider 管理
- `more_core/more_core/mcp/` — MCP Client + Server
- `more_core/more_core/a2a/` — A2A 协议
- `plugins/` — 3 个行业插件 (mahjong, minesweeper_game, minesweeper_agent)

### 验证脚本
- `comprehensive_test.py` — 综合试运转
- `status_dashboard.py` — 状态检视窗口
- `module_audit.py` — 全模块故障排除