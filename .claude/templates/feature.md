请实现以下功能：

## 工作流

1. **设计**: 先在代码库中找到相似功能的实现（read before write）
2. **测试先行**: 先写测试定义意图，再实现
3. **实现**: 最小代码，不做投机式抽象
4. **验证**: `make test && make lint && make typecheck` 全部通过
5. **内容边界**:
   - API 路由 → `api/routers/`
   - 业务逻辑 → 对应模块层
   - 工具/动作 → `hands/`
   - 数据模型 → `core/types.py` 或模块内 `BaseModel`
