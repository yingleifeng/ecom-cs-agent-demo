# 电商商家客服 AI Agent Demo

这是一个使用模拟数据、只读、可追踪的客服 AI Agent 学习型原型。

## 本地启动

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
uvicorn customer_agent.api:app --reload
```

启动后访问 <http://127.0.0.1:8000/> 查看交互式 Demo，访问 <http://127.0.0.1:8000/docs> 查看 API 文档。

也可以直接运行一条请求：

```bash
PYTHONPATH=src python -m customer_agent.cli --user-id u_001 --message "我想问一下订单能不能退"
```

当前版本完成退款资格主链路、意图分流和短期会话定位能力：统一输入/输出、只读约束、订单/物流/售后查询、最近订单列表、候选订单选择、规则决策和基础 trace。可用 `MULTI_AGENT_ENABLED=true` 默认启用确定性多 Agent 角色编排，也可在请求中通过 `mode` 显式选择 `single_agent` 或 `multi_agent`。两种模式共用相同工具和规则；当前 mock 角色不调用模型，因此 token 用量和模型费用为 0。

多轮对话评测集位于 `data/multiturn_eval_v1.json`，包含 40 个案例，覆盖槽位补充、指代消解、任务切换、会话终止、工具失败、越权和记忆管理。每个案例标注逐轮意图、槽位变化、期望工具路径、转人工标记和最终会话状态。

## 运行评测

使用项目虚拟环境运行全量测试和多轮回放：

```bash
.venv/bin/python -m pytest
PYTHONPATH=src .venv/bin/python -m evals.runner \
  --dataset data/multiturn_eval_v1.json \
  --report reports/baseline_v0_ticket04.json
```

`reports/baseline_v0_ticket04.json` 保存每轮实际响应、trace、失败断言和汇总指标。评测器会把订单、物流、售后、政策检索和最近订单列表计入工具路径准确率；长期记忆和商品尺码等未实现能力单独标记为 `unsupported`。Ticket 04 的人工验收步骤见 [`docs/Ticket04验收.md`](docs/Ticket04验收.md)。

单 Agent 与多 Agent 的同数据对比可运行：

```bash
PYTHONPATH=src .venv/bin/python -m evals.compare_agent_modes \
  --dataset data/multiturn_eval_v1.json \
  --report reports/agent_mode_comparison.json
```

也可以直接双击 `demo.html` 查看前端模拟预览；通过 FastAPI 地址打开时，页面会使用真实的 `/chat` 编排入口。

工具后端的选择建议和本地工具清单见 [`docs/工具契约.md`](docs/工具契约.md)：本地模式适合开发、测试和离线演示；需要跨应用复用或独立部署工具服务时再使用 MCP。当前 MCP 与本地模式都读取同一套模拟数据，不代表已接入真实电商平台。
