# 本地工具 vs MCP 对比报告

**对比维度**：接入方式（本地函数调用 vs MCP stdio 协议）  
**测试场景**：5 个代表性场景，覆盖 0-4 次工具调用  
**运行命令**：
```bash
# 本地工具模式（默认）
uvicorn customer_agent.api:app --reload

# MCP 模式
MCP_ENABLED=true uvicorn customer_agent.api:app --reload

# 或在 demo 页面右上角"工具模式"下拉切换
```

---

## 核心对比数据

| 场景 | 工具调用次数 | 本地工具延迟 | MCP 延迟 | 倍数 |
|---|---|---|---|---|
| 未发货退款 | 3 | 2.72ms | 286ms | 105× |
| 已发货未签收 | 3 | 1.11ms | 291ms | 262× |
| 越权订单 | 1 | 0.28ms | 102ms | 364× |
| 定制品例外 | 3 | 1.08ms | 298ms | 276× |
| 缺少订单号 | 0 | 0.18ms | 0.30ms | 持平 |
| **平均** | — | **1.07ms** | **195ms** | **~180×** |

两种模式的业务结论（eligibility、转人工判断）完全一致，结果一致性 100%。

---

## 结果解读

### 延迟差距来自哪里

**没有工具调用时两者延迟持平**（0.18ms vs 0.30ms）。延迟差距完全来自 MCP 协议栈的固定开销，与查询的数据无关：

每次 MCP 工具调用需要：
1. 启动子进程（MCP server）
2. 发送 `initialize` 握手消息
3. 发送 `tools/call` 请求
4. 等待子进程处理并返回结果
5. 解析 JSON-RPC 响应

这套流程每次约 **95-100ms**，3 次工具调用累计约 **290ms**，无论查什么数据都是这个成本。

### 业务结论为什么完全一致

MCP client 和本地工具底层调用同一套数据读取逻辑（`LocalReadOnlyTools`），只是 MCP 在外面包了一层协议转换。结果完全相同，验证了"MCP 只改变接入方式，不影响业务逻辑"这一设计原则。

---

## 两种模式的适用场景

| 维度 | 本地工具 | MCP |
|---|---|---|
| 延迟 | 微秒级（<3ms） | 百毫秒级（~100ms/次调用） |
| 适用场景 | 工具在同一进程内，开发/测试/离线演示 | 工具由独立服务提供，需跨团队复用 |
| 工程成本 | 直接函数调用，零配置 | 需维护 server 进程，处理进程通信 |
| 复用性 | 只有本 Agent 能用 | 任何支持 MCP 的 Agent 都能直接接入 |
| 权限治理 | 无独立治理层 | 可在 server 层统一做权限和版本管理 |

### 什么时候应该用 MCP

满足以下任意一条时，MCP 的工程价值能覆盖其延迟代价：

1. **跨团队工具**：`get_order` 是交易部门维护的服务，`get_logistics` 是物流部门的——各团队只需维护自己的 MCP server，Agent 团队不需要了解每个系统的内部实现
2. **多 Agent 复用**：同一批工具被 5 个不同业务线的 Agent 使用，统一包装成 MCP server 后每个 Agent 直接接入，无需重复开发
3. **独立部署**：工具需要独立扩容、灰度发布，不能和 Agent 绑定在一起

### 这个 demo 的判断

**当前场景不需要 MCP**，本地工具完全够用：
- 所有工具在同一进程内，没有跨团队调用
- 只有一个 Agent，不存在工具复用需求
- 工具本质是读 JSON 文件，独立部署没有意义

MCP 在 demo 中的价值是**对比实验**——亲眼看到协议层开销的数字（~180× 延迟增加），帮助在实际项目中做出有数据支撑的技术选型判断。

---

## 如何复现

```bash
# 环境准备
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

# 手动对比（修改 tool_mode 参数）
PYTHONPATH=src python3 -c "
from customer_agent.orchestrator import CustomerAgent
from customer_agent.schemas import CustomerRequest
import time

for mode in ('local', 'mcp'):
    agent = CustomerAgent()
    t0 = time.perf_counter()
    result = agent.handle_request(CustomerRequest(
        message='订单还没发货，可以退款吗？',
        user_id='u_001', session_id='bench',
        order_id='o_1001', tool_mode=mode,
    ))
    print(f'{mode}: {round((time.perf_counter()-t0)*1000,2)}ms  eligibility={result.response.eligibility}')
"
```

---

## 下一步

- [ ] 接入真实外部服务后重新运行，记录真实网络延迟下的对比数据
- [ ] 测试 MCP server 独立部署场景（`MCP_SERVER_COMMAND` 环境变量指向远程服务）
