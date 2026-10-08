# 本轮查询进度：memory.local-query-session.v1

2026-09-14，局部 C/R，未加载生产宿主。采用[查询进度专题的 A 包](../../../../../astrbot_plugin_private_companion/docs/MEMORY_QUERY_SESSION_DESIGN_V0.md)，复用 Memory 同轮内存和原 owner 工具，不写第二份记忆库。

## 接入和返回

`MemoryCompanionService.tool_query(event, operation, parameters)` 接收[request Schema](./schemas/request.schema.json)，返回[result Schema](./schemas/result.schema.json)。支持原有 recall/sources/navigate/events 与只读 status；不接受身份、SQL、可执行代码或语义记事参数。身份和轮次由宿主解析，Memory 实例代际参与内部键。

模型默认仍使用四个原查询工具。开启 `memory_tools.enable_query_progress` 后，原生工具通过 `query_for_model` 返回独立封套：`result` 是本次原 owner 结果，`progress` 是短进度，`operation_id` 关联本次操作。source/event 内层仍分别符合其现有封闭 v1；服务端的 `tool_sources/tool_events/tool_recall/tool_navigate` 仍返回原类型并登记实际调用。关闭开关即恢复原生工具的原返回方式。

`memory_companion_query` 注册完整本地输入格式，但当前普通请求只向模型展示很小的 status 格式，避免再携带整套查询 Schema。投影只修改本次请求副本，保留宿主实际提供的工具及 active 状态；工具未提供、开关关闭、作用域不可用或绑定失败时不扩展能力。状态工具按需使用，不要求每次查询前后调用。

这一默认接法来自隔离模型对照：仅提供统一入口的迭代增加了一周题的无效调用，保留原工具有较少无效调用。小样本不证明所有问法都更快，详见[验证记录](../../../../../astrbot_plugin_private_companion/docs/evaluations/S3_QUERY_PROGRESS_20260914.md)。

## 进度与资源

短进度包括本轮操作数、在途数、已用/剩余步骤、已返回来源/当前有效来源/部分片段数、有效续页数、最近两次操作。默认展示上限 900 字符只限制进度，不截断原结果。status 返回有界历史及仍有效的来源版本、已读区间、可补读偏移、游标和原期限，展示上限 12000 字符；省略数量显式返回。

来源过期、数据/权限 revision 变化后，旧细节及游标不再展示。已成功消费的页不再标为可续；同轮记录保存不会把来源 120 秒期限延长。`next_excerpt_offset` 是已读区间之后的第一个缺口，可能为 0；null 只说明这个可读文本已覆盖，不证明捕获完整或所有事件已查全。`current_context=unknown` 表示宿主没有证明这些原文仍在本次模型上下文中。

sources/navigate/events 保持原有默认 3 步，共用额度；失败发生在预留后也如实占用。ordinary recall 不在这 3 步内，现行限制是每次最多 10 条候选，**没有独立的次数额度**。`recall_calls` 为调用观测数，`recall_item_limit` 为返回条数上限，均不代表剩余调用数。Host 的模型次数/token/deadline 未接入本地状态，不推断为免费或无限。usage 缺失标未知，程序不填零消费。

账目最多保留 24 条已结束操作、合计约 16 KiB；更早条目可省略，累计次数与步骤仍保留。事件输入只留目标/操作/行数和 SHA-256，不重复保存长引文。详细状态不重发 recall 的条件、正文或记忆 ID，也不重发 navigate 的 memory_ids；这些需要逐条有效期及外部 P5 重验，A 先保留原工具结果和内部有界记录。状态读取只核对本地版本元数据，不再次查询资料或调用模型。

## 当前边界与验证

v1 没有跨轮/重启续跑、自动摘要、固定查询顺序、语义结论存档、统一新预算或重复正文缓存。可选便笺与同轮回看已另接 [v2](../v2/README.md)，只有当前请求支持时才使用，不改变 v1 格式；压缩后最终请求可见性仍 unknown。大资料索引及成本对照留到 C，本地 profile 不声明公共 MemoryQuery 已就绪。

相关测试在 `tests/test_query_session.py`，涵盖实际原文/事件/导航接线、兼容入口、并发、取消、预留后失败、过期/修订/撤权、缺口和原生工具投影；既有来源及事件测试继续校验其原类型。性能使用 `scripts/benchmark_query_progress.py` 的临时库对照，模型使用 `scripts/evaluate_recall_model.py --query-progress`；不重载插件、不写生产库、不发平台消息。
