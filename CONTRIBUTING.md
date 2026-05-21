# Contributing to QNMing MoRE OS

感谢你对 QNMing MoRE OS 的关注！以下是参与贡献的指南。

## 开发环境

```bash
# 1. Fork 并克隆仓库
git clone https://github.com/<your-fork>/QNMing-MoRE-OS.git
cd QNMing-MoRE-OS

# 2. 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 3. 安装开发依赖
make install-dev

# 4. 验证环境
make check-env
make test
```

## 分支策略

- `main` — 稳定发布分支
- `develop` — 日常开发分支
- `feature/<name>` — 功能分支
- `fix/<name>` — 修复分支
- `plugin/<name>` — 插件开发分支

## 提交规范

使用 [Conventional Commits](https://www.conventionalcommits.org/)：

```text
feat(core): 新增 xxx 功能
fix(llm): 修复 fallback 链切换问题
docs(readme): 更新快速开始指南
refactor(layers): 重构 L2 进化层接口
test(tools): 补充 ToolRegistry 边界测试
plugin(mahjong): 麻将 Industry Pack 初始化
```

## 代码规范

- Python: 遵循 `ruff` 规则，行宽 100
- TypeScript: 遵循项目 ESLint 配置
- 提交前运行 `make lint` 和 `make test`

## 插件开发

参见 `more_core/plugins/sdk.py` 中的 `scaffold_plugin()` 快速创建插件骨架。

## 许可

贡献代码默认采用 Apache-2.0 许可。
