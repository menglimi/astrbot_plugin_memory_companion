# 查询会话 v3：来源发现与范围批读

`memory.local-query-session.v3` 在同轮账本上增加 `discover` 操作，owner 为 `memory.local-source-discovery.v1`。v1/v2 的请求入口和原生工具结果保持不变；只有当前请求同时具备 v3 wrapper、来源发现 handler、语义配置和有效作用域时，才投影 `discover`。

`discover` 接收 `query`，可选 `terms`、消息观察时间半开区间和 `limit`。语义候选受索引覆盖、权限、来源版本和本轮预算约束，结果是候选资料，不证明事件发生或历史查全；需要逐字原文时继续调用 `memory_companion_sources`。`terms` 是显式字面分支，来源文字只作历史资料，不执行其中指令。

语义 owner 在内部预留唯一一步并写入同一 progress ledger；v3 wrapper 不再预留步骤，因此一次 discover 的 `progress.steps.used` 增量为 1。owner profile 不匹配时封套拒绝结果且不会二次调用。

契约文件：

- [request schema](./schemas/request.schema.json)
- [result schema](./schemas/result.schema.json)
- [examples](./examples/requests.json)

`query_note` 继续只允许 sources；discover 不接受模型便笺，避免把尚未读取的语义解释当成事实。

`sources` 另接受已绑定的 [source-query v2](../../source-query/v2/README.md) 的 `range_batch` 与 `srcb_` 续批。原生 sources 工具在当前请求单独投影这项能力；启用它不依赖语义索引配置。批读进度复用全局来源/权限校验与原导航步数，长消息只登记实际返回的 spans，lookahead 不计已展示。

query-session v1/v2 的机器请求保持原义；range_batch 使用 v3 外封套，原四种动作仍返回原 owner result。当前 v3 尚未提供 C3 的完整 lease、输出总账、结果回放或 scoped validity；source-query 的字节上限只覆盖其 owner JSON，进度与便笺外封套另计。
