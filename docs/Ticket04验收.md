# Ticket 04 验收说明

## 启动

在项目根目录执行：

```bash
.venv/bin/python -m pytest
uvicorn customer_agent.api:app --reload
```

浏览器打开 <http://127.0.0.1:8000/>，前端默认使用 `u_001` 和固定会话。点击“新建会话”可以验证会话边界。

## 人工验收路径

### 1. 首轮缺少订单号

输入：

```text
我想退款
```

预期：

- 回复要求补充订单号
- 首轮不调用 `list_recent_orders`
- 会话状态为 `needs_order_id`

### 2. 明确要求查看最近订单

新建会话后输入：

```text
我有几笔订单，查最近那笔
```

预期：

- 只展示当前用户的最近订单
- `u_001` 只能看到 `o_1001`、`o_1002`、`o_1003`
- 每项只包含订单号、商品名、订单状态和下单时间
- Trace 中出现一次 `list_recent_orders`

继续输入：

```text
第二个
```

预期：

- 选中 `o_1002`
- 继续调用 `get_order`、`get_logistics`、`get_after_sales` 和政策检索
- 响应中的 `order_options` 清空
- 因为 `o_1002` 已发货但未签收，当前规则会转人工

### 3. 短期指代

新建会话后依次输入：

```text
订单 o_1001 能退款吗
这单是什么状态
```

预期第二轮仍使用 `o_1001` 查询，不从用户文本或短期记忆中改变 `user_id`。

### 4. 追问上限

新建会话后连续输入不包含有效订单号的退款问题。前两次保持澄清，第三次：

- `need_human=true`
- `session_state=handoff`
- 不再继续展示或查询其他用户的订单

## 命令行验证

单轮调用：

```bash
PYTHONPATH=src .venv/bin/python -m customer_agent.cli \
  --user-id u_001 \
  --message "我有几笔订单，查最近那笔"
```

需要查看完整结构化结果和 Trace 时使用 API：

```bash
curl -s http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"u_001","session_id":"manual-ticket04","message":"我有几笔订单，查最近那笔"}'
```

## 自动评测

```bash
.venv/bin/python -m pytest
PYTHONPATH=src .venv/bin/python -m evals.runner \
  --dataset data/multiturn_eval_v1.json \
  --report reports/baseline_v0_ticket04.json
```

报告中的 `summary` 是当前实现的真实分数；`cases` 里可以按 `case_id` 查看每轮实际响应、工具路径和最终状态。
