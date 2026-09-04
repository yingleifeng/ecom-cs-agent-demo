# 电商商家客服 AI Agent Demo

这是一个使用模拟数据、只读、可追踪的客服 AI Agent 学习型原型。

## 本地启动

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
uvicorn customer_agent.api:app --reload
```

启动后访问 <http://127.0.0.1:8000/docs> 查看 API 文档。

也可以直接运行一条请求：

```bash
PYTHONPATH=src python -m customer_agent.cli --user-id u_001 --message "我想问一下订单能不能退"
```

当前版本完成票据 01 的基线：统一输入/输出、只读约束、客服请求编排入口和基础 trace。RAG、业务工具、规则决策、短期记忆和 MCP 将在后续票据中接入。
