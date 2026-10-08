# C2b 原文查询基线审阅 · 2026-10-08

本文记录插件仓库当前代码与 v1 契约的审阅结果，用于后续 C2c-1 片段/依赖工程。它是代码基线审阅，不是 SQB 验收，不证明短词索引的完整性、部署性能、真实 owner 加载或生产查询收益。

## 范围

- 公共基准：[C2b 设计](../../../astrbot_plugin_private_companion/docs/MEMORY_QUERY_SESSION_DESIGN_V0.md#source-query-c2b-design)、[接口版本决定](../../../astrbot_plugin_private_companion/docs/MEMORY_PROPOSAL_QUERY_CONTRACT_V0.md#source-query-c2b-compatibility)、[SQB-01--12](../../../astrbot_plugin_private_companion/docs/MEMORY_COUNTEREXAMPLE_EVAL_V0.md#source-query-c2b-evaluation)
- 本地读取实现：`core/source_query.py`、`MemoryStore._query_source_page_sync`
- 本地索引维护：`MemoryStore._ensure_source_query_indexes_sync`
- 当前封闭结果契约：`docs/contracts/source-query/v1/`
- 读取凭证和来源版本：`core/source_evidence.py`

## 当前行为

| 项目 | 现有行为 | 审阅结论 |
| --- | --- | --- |
| 授权 | SQL 在分页前按 scope、session、Bot、平台、人格和用户/群目标过滤；序列化前再次核对原行 | 不能把候选 ID 或 FTS 全局命中当授权；新索引必须沿用此 owner 边界 |
| 长词候选 | `timeline_source_fts` 是外部内容 FTS5 trigram；只有所有 term 长度都至少 3 时才查询 FTS 候选，再用 `instr(lower(content),lower(term))` 保持现有命中语义 | 原文核对能排除多余候选，不能补回未进入 FTS 候选的匹配行 |
| 短词与混合词 | 任一 term 少于 3 字符时整组条件沿授权分区做原字面 OR 扫描 | 两字词和长短混合词还没有设计中的双字候选/union 路径；v1 path 不能伪报新路径 |
| trigram 维护 | timeline insert/delete/content-update 触发器更新 FTS；缺表、缺版本标记或版本不符时初始化执行全量 rebuild | 普通触发器维护与定向编辑/删除测试已有依据；未审计触发器丢失、部分损坏、只读旧库和大库启动 rebuild 的成本边界 |
| 时间分页 | search/range 使用完整 `(julianday(occurred_at),created_at,id)` 边界；context 前后查询现在额外加等价的 `<=/>=` 时间条件 | 新测试确认并列时间下 tuple 分页不重不漏，并观察到来源时间索引范围计划；search/range 性能尚未测 |
| 版本与游标 | 来源 revision 是全 timeline 修订计数；游标绑定来源 revision、查询、身份及策略 revision | 其它会话变化可能使游标失效；属于现行保守边界，不作 C3 分区账本能力声明 |
| 结果含义 | coverage.path 只允许 v1 声明的路径，event coverage 固定 `not_established` | 空结果不是事件不存在；新候选不改变语义覆盖或完整性 |

## 已运行检查

- `tests/test_source_query.py`：42 passed，含短词扫描、长词 FTS、字面操作符、授权、编辑/删除、重建、时间分页及 context 索引范围。
- `tests/test_source_query_contract.py`：11 passed，v1 request/result schema 与拒绝用例通过。
- 本轮合并回归：语义依赖、来源捕获、来源查询及 v1 契约共 75 passed。

这些夹具未覆盖 SQB 全部反例，也未测量大库 trigram 写入 P95、dirty 积压、磁盘/WAL/RSS、SQL VM 工作量、锁等待、只读索引缺口或宿主中的原始 owner。设计探针中的合成结果仍不能作为 runtime acceptance。

## 审阅结论

C2b 的 v1 字面结果语义和授权边界可作为旧路径基线；C2b 整包未冻结或验收。新增双字候选必须在同一读取快照中合并 trigram、双字、dirty/缺覆盖扫描，并逐项执行原 `instr` 核对、统一去重排序和 lookahead；任一分支不完整时应报告旧路径或明确降级，不能返回看起来完整的空结果。旧 v1 和 A/B query-session 入口保持原义。

按当前框架路线，本地已接入 context 等价时间范围条件；C2c-1 已有按 generation 的语义依赖/dirty、稳定 ID 历史扫描、顺序变更邻居展开和写入前来源围栏。尚无 embedding worker、generation 激活/完成证明或语义检索消费者。该数据基础不改变 SQB/SQS 状态；代码范围与回归证据见下方 C2c-1 记录。

## 2026-10-08 C2c-1 确定性维护增量

本轮在上述基线上补入一段本地维护实现，详见 [C2c-1 维护记录](./source-semantic-c2c1-maintenance-20261008.md)。它不构成 C2c 语义检索完成，也不改变 C2b/SQB/SQS 验收状态。

- `scan_generation_sources` 按稳定来源 ID 做有界 keyset 遍历，绑定 generation 的 `base_sequence` 与完成游标；来源变更仍进入独立 semantic dirty，因此扫描期间插入到游标之前的旧时间来源不会被历史页静默漏掉。
- 扫描、原文读取和投影提交都要求 owner 授权回调；构建范围可限定一个 owner partition。扫描只返回来源引用和版本，读取时重验来源版本，不把第二份正文写入索引表。
- timeline 触发器逐次保存旧/新顺序快照。维护器按旧/新时间位置查同一来源分区的最近邻，给受影响 anchor 入队并让窗口文档 stale；覆盖新插入旧时间、删除、时间/归属变更。语义 dirty 仅在对应顺序变化展开后允许确认。
- `build_semantic_window` 给出有字符上限的锚点/邻居拼接与各自 Unicode 码点 span。投影提交重新检查 generation config hash、全局来源修订、owner、来源版本、输入正文与 span 一致性及最近邻关系。

该切片目前没有后台调度/embedding 调用、取消和额度协调、generation 完成与激活流程、向量资格查询或语义 discovery 消费者。全局 source revision 是保守围栏；仍需实测大库扫描与顺序 dirty 积压，并验证历史回填期间的恢复、provider 结果形状和真实 owner 宿主。窗口候选在顺序 dirty 尚未展开时必须由未来的查询消费者排除；当前没有该消费者，故不能声明索引可用于查询。
