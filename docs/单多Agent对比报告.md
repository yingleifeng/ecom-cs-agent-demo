# 单 Agent vs 多 Agent 对比报告

**评测集**：`data/multiturn_eval_v1.json`（v1.0）  
**案例数**：40 个，79 轮  
**运行命令**：
```bash
PYTHONPATH=src python3 -m evals.compare_agent_modes \
  --dataset data/multiturn_eval_v1.json \
  --report reports/agent_mode_comparison.json
```

---

## 核心对比数据

| 指标 | 单 Agent | 多 Agent | 差异 |
|---|---|---|---|
| 意图准确率 | 77.2% | 77.2% | 持平 |
| 槽位准确率 | 87.3% | 87.3% | 持平 |
| 工具路径准确率 | 54.1% | 54.1% | 持平 |
| 转人工准确率 | 79.8% | 79.8% | 持平 |
| 转人工召回率 | 82.4% | 82.4% | 持平 |
| 最终会话状态准确率 | 60.0% | 60.0% | 持平 |
| **平均每轮延迟** | **0.26 ms** | **0.33 ms** | **多 Agent 慢 27%** |
| Agent 角色调用次数 | 0 | 185 | 多 Agent 额外开销 |
| 工具调用总次数 | 79 | 79 | 持平 |
| 失败工具调用 | 3 | 3 | 持平 |
| 失败定位率 | 100% | 100% | 持平 |
| 结果一致性 | — | **100%** | 两种模式结论完全一致 |
| Token 用量 | 0 | 0 | mock 阶段无模型调用 |
| 模型费用 | $0.0000 | $0.0000 | mock 阶段无费用 |

---

## 结果解读

### 质量指标为什么完全一致

当前多 Agent 模式将编排拆分为四个角色（OrchestrationAgent、PolicyAgent、FactsAgent、HandoffAgent），但这四个角色是**确定性的 mock**，内部逻辑与单 Agent 共用同一套工具契约和规则决策引擎。因此在 mock 阶段，两种模式的决策路径完全相同，所有质量指标一致，结果一致性达到 100%。

质量指标的差异将在引入真实 LLM 后出现：多 Agent 模式下每个角色独立调用模型，意图分类、政策检索和事实核实的错误不会互相掩盖，理论上可以做更精细的错误归因。但这也意味着任何一个角色的模型输出出现偏差，都可能影响最终结论。

### 延迟为什么多 Agent 更慢

多 Agent 模式产生了 185 次额外的角色调度调用（`agent_*` 事件），即使每次调度本身只是函数调用，累积起来也带来了 27% 的延迟增加（0.26ms → 0.33ms）。

**在 mock 阶段这个差距很小，但换成真实 LLM 时差距会被大幅放大**：每次角色切换都涉及一次模型推理，延迟会从毫秒级跳到数百毫秒甚至秒级。多 Agent 的延迟代价在真实场景中是需要认真权衡的因素。

### 什么时候多 Agent 才有价值

根据当前数据，在 mock 阶段多 Agent 没有带来质量提升，只有延迟增加。多 Agent 真正的价值会在以下情况显现：

1. **引入真实 LLM 后**：不同角色可以使用不同规模的模型（政策检索用小模型、复杂判断用大模型），在质量和成本间取得平衡
2. **业务复杂度提升后**：当单 Agent 上下文窗口不足以容纳所有工具定义和历史记录时，拆分职责可以降低每个角色的认知负担
3. **并行处理场景**：政策检索和订单查询可以并行，减少串行等待时间

### 当前指标中的已知限制

- **工具路径准确率 54.1%**：不代表答案错误，而是 Agent 实际调用的工具序列与评测集期望路径不完全一致。这是过程指标，反映决策路径的规范性，与结果指标独立看待。
- **最终会话状态准确率 60%**：部分场景的会话终态（resolved / handoff / cancelled）没有正确落地，是下一步迭代的方向。
- **5 个 unsupported turns**：评测集中标注了 `write_long_term_memory`、`recall_long_term_memory`、`retrieve_product_size` 的场景，当前版本未实现，计为不计分。

---

## 如何复现

```bash
# 环境准备
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

# 运行对比
PYTHONPATH=src python3 -m evals.compare_agent_modes \
  --dataset data/multiturn_eval_v1.json \
  --report reports/agent_mode_comparison.json

# 完整评测（含逐轮明细）
PYTHONPATH=src python3 -m evals.runner \
  --dataset data/multiturn_eval_v1.json \
  --report reports/baseline_v0.json
```

详细逐轮结果见 `reports/agent_mode_comparison.json`。

---

## 下一步

- [ ] 接入真实 LLM 后重新运行本对比，记录延迟和准确率的实际变化
- [ ] 分析工具路径准确率 54.1% 的失败案例，找出主要失败模式
- [ ] 补充 `write_long_term_memory` 等 5 个 unsupported 场景，提升评测覆盖率
