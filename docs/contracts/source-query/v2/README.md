# source-query v2：消息时间范围批读

本地 profile `memory.local-source-query.v2` 目前只交付 C3 的 `range_batch` 分支。旧 `search/range/context/read` 继续由 v1 owner 返回原 profile，原 `range` 仍按消息时间倒序分页。这里不代表整个 v2 框架或 C3 共同资源、回放、分区失效已完成。

## 请求和绑定

首次传 `action=range_batch` 和带时区的 `start_at/end_at`，按消息观察时间的 `[start,end)` 正序读取。续批只传 `cursor`，允许原工具的空默认字段。`terms`、owner 条件、`source_ref`、非零 `limit/excerpt_offset` 均不适用。

`memory_tools.enable_source_query_v2` 默认关闭。初始化核验原生 sources handler 的模块与完整签名后标记能力，每个请求仅投影当前可用能力并绑定身份/实例/轮次。未绑定时明确拒绝。关闭查询进度不关闭批读的原导航预算计量；开启进度时批读使用 query-session v3 外封套，便笺仍只引用此前实际已读来源。

## 批量和游标

默认 owner 返回预算为 12288 UTF-8 字节、48 条授权消息、64 个片段、每片最多 800 字符。计量包含 source-query JSON 的正文、引用、覆盖和 usage 自身，`usage.returned_bytes` 为实际紧凑序列化体积。query-session 外层进度和便笺不包含在此上限内；Host 总上下文和 Token 预算仍为 unknown。本阶段仍共用既有单轮导航步数，不提供新的 lease 或并发资源账本。

SQL 在授权分区内按 `(julianday(occurred_at),created_at,id)` 有界正序读取，额外一条 lookahead 只判断续页；不扫描 COUNT，不按关键词或相似度删掉范围内消息。单次数据库读取有 2 秒中断保护。异常历史正文超过 262144 字符或元数据超过 65536 字符时不加载完整值并明确拒绝，不签发跳过该行的游标。

`srcb_` 是独立、不透明且限本轮的内存句柄，绑定范围、固定配置预算、全局 source/policy revision、下一行稳定键和真实正文 offset。120 秒期限不会因续批、status 或便笺而延长。旧 `src_` 游标不能混用。任一来源或权限版本变化后失效，尚未启用 scoped validity。相同页重复请求仍按旧去重语义拒绝，未交付结果回放或在途合并。

## 覆盖含义

| 字段 | 可证明的范围 |
| --- | --- |
| `coverage.traversal` | 当前授权与版本下连续访问的消息边界、累计消息数、是否到 EOF；预取行不计已展示 |
| `coverage.presentation` | 实际返回片段和字符、完整返回的消息数、抑制缺口、当前长正文是否待续 |
| `coverage.interpretation` | 事件覆盖固定 `not_established`；当前上下文与捕获完整性没有宿主证明 |
| `coverage.dependencies` | 明确使用两条全局版本，不能冒充更细的分区证明 |

长消息一批可以返回多个同版本连续片段，余文保留在当前行/offset；即使最后一行已访问且 traversal EOF，正文有余文时 presentation 仍 incomplete。脱敏/内部占位过滤的授权行可以前进并计为缺口，不能认定模型读过其正文。无权限行不披露 ID、计数或过滤理由。

最小片段与必要封套放不下时返回 `range_batch_budget_too_small`，不签发空推进游标。只有同一有效页链真正到尾、正文全部返回且没有抑制缺口，presentation 才为 complete；该状态仍不证明事件语义查全、范围外更正不存在或消息全部捕获。

## 验证

`tests/test_source_query_v2.py` 验证真实存储/owner/原生工具绑定，以及跨日与并列时间、UTF-8 预算、长消息连续偏移、EOF 展示缺口、权限/版本/轮次/期限、取消和旧预算兼容。Schema 与 examples 同步验证；未运行真实 embedding 或生产宿主问答验收。
