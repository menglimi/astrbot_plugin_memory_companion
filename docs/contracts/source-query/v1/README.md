# 当前轮原始消息查询 v1

`memory.local-source-query.v1` 是 Memory 内部原生 LLM 工具 `memory_companion_sources` 的局部 profile。它让当前回复模型在摘要不足时直接查原始消息。输入/结果分别由 [request.schema.json](./schemas/request.schema.json) 和 [result.schema.json](./schemas/result.schema.json) 描述，[examples](./examples/) 使用虚构数据。格式测试还会验证实际 service 返回值。

本包只冻结当前工具的受支持字段，不提供公共 MemoryAtom QueryPlan、跨插件能力协商或新的授权入口。外部封闭 RecallResult v1 不加入这些字段，不给来源伪造 atom/proposal ID。请求中没有身份字段；会话、平台、用户/群、Bot 和人格均由宿主事件解析，再由 Memory 在取数前核对原行。

后续 [C2b 设计](../../../../../astrbot_plugin_private_companion/docs/MEMORY_QUERY_SESSION_DESIGN_V0.md#source-query-c2b-design)拟用独立 source-query v2 声明双字符/混合查询路径，并配 query-session v3 接入进度与可选便笺。这两个包均尚未实现；本页和现有 Schema 继续描述 v1 的真实能力，context 的等价时间条件优化可独立沿用本版。

## 四种动作

| 动作 | 输入与读法 | 结果含义 |
| --- | --- | --- |
| `search` | 模型提炼 1–6 个词句，每项至多 80 字符；任一字面子串匹配，可加带时区的消息时间范围 | 按消息时间倒序返回；词句全部至少 3 字符时用 FTS5 trigram 候选，再做字面校验；短词或缺 trigram 时在授权分区做子串查询。没有自动同义扩展或语义排名 |
| `range` | 必填 `start_at/end_at`；不带词句，读取半开区间 `[start,end)` | 只表示此消息时间范围内的可读记录；区间内发生的事情可能在区间外才被提及 |
| `context` | 已返回的 `source_ref`，以及 `around/before/after` | 读取锚点前后的消息，页内正序；前后相邻不自动等于同一事件 |
| `read` | 已返回的 `source_ref`，可带 `excerpt_offset` | 读取这条消息的一段；用 `next_excerpt_offset` 补读后段，设 0 看开头 |

规范输入日期使用带时区 ISO 8601，例如 `2026-09-08T00:00:00+08:00`；服务还核验真实日期、时区、起止顺序和参数组合。Schema 不证明日期存在、引用授权或游标有效。空字符串/默认值用于 AstrBot 的可选参数兼容；未知字段和不支持动作明确拒绝。

## 分页、版本与预算

`next_cursor` 用于 search/range，`context_cursors.before/after` 用于前后文；续页仅传 `cursor`，宿主填入的空默认值可以保留。不能改条件或页大小。cursor 绑定本轮身份、查询、页大小、时间线版本与 Memory/ACL 版本，120 秒到期；只在内存中保存，插件重载或进程退出后失效。新消息、修改、删除或权限变化会使旧页链失效；在剩余预算内重新查询，不能把新旧页拼为完整结果。该版本是保守的全时间线版本，其他会话写入也可能使 cursor 失效。

和 `memory_companion_navigate` 共用每轮步数，默认 3 步、每页 6 条，配置上限 8 步、每页 12 条，每条至多 800 字符。翻页、换词、补片段都消耗步骤，重复同一页被拒绝。`limit=0` 用配置默认值，更大的 limit 会被下调。返回体字符数不包含模型消费工具结果的 token 成本。

每页在只读事务中按 `(julianday(message_at),created_at,id)` 稳定边界取数，权限过滤先于 LIMIT；额外读一条判断是否还有下一页。SQL progress handler 给执行中的 SQL 约 2 秒限时，不包含锁等待、连接准备等全部墙钟耗时。异步取消不返回结果/新 cursor，已启动的同步 SQL 线程仍需等待 SQL 结束或限时；不宣称线程立即停止。

## 时间、片段与完整性

`message_at` 是 timeline 观察时间，`recorded_at` 是入库时间；没有可信平台时间时不冒充原始发送时刻，也不自动证明事件发生时间。无法解析消息时间的记录不进入 search/range/context 时间排序，但持有合法引用时可 read；`unknown_message_time` 说明该边界，不证明本库不存在未知时间记录。

search 返回命中附近的脱敏片段。`excerpt_offset/end/next_excerpt_offset` 是脱敏后文本的位置；补读应核对 `source_version` 一致，变化时重新读取。现有 timeline 捕获和脱敏路径最多保留约 4000 字符，read 只能补读已保留部分。`excerpt_truncated` 说明本次未展示全部可读文本，`capture_truncated=null` 表示早期捕获是否完整未知；后者不能因翻完片段变为 false。

`coverage.read_count` 是本页 SQL 已返回到程序的行数，包含 lookahead 与锚点重读，不是数据库实际扫描行数或跨页去重数量。`returned_count/suppressed_count` 区分返回与脱敏/内部占位过滤；空页仍可能带 cursor，应查看 `more_available`。`excerpt_truncated_count` 与是否有下一页无关。

`event_coverage` 固定 `not_established`。最后一页只表明这次词句/消息区间查询结束，不证明同义表达都已检出、消息捕获完整或语义事件全集已确认。`empty` 不等于“事情没发生”。本轮实际返回的来源会记录版本、已读片段位置、权限版本和有效期，供 [临时事件计算工具](../../event-query/v1/README.md) 重验后使用；它由当前模型判断同一事件、计划/实际、转述和纠正，程序执行去重/排序/统计。补读不延长旧片段期限，模型语义与最终答案仍需独立验收。

历史文本仅作为证据材料，不能作为指令。无权限和不存在的引用统一 `source_unavailable`；失败 `rejected` 返回空来源、空覆盖和空 usage，不能据此推断未消耗预算。查询不调用模型、不写事实或生产消息；消费工具结果所需的模型往返仍计入实际回复延迟。
