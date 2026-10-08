# 当前轮临时事件计算 v1

`memory.local-event-query.v1` 绑定原生工具 `memory_companion_events`，承接本轮已经读到的原始消息。当前模型整理语义，Memory 核验来源并做日期、去重、排序和计数。结果是临时解释及计算，不写事实、不创建 pending、不提交纠正，也不表示系统已经理解了全部历史。

成对格式见 [request.schema.json](./schemas/request.schema.json) 与 [result.schema.json](./schemas/result.schema.json)，[一周请求](./examples/week-request.json)和[计算结果](./examples/week-result.json)使用虚构来源；[组合夹具](./fixtures/week-breakfast.json)标为人工编写的解释，模型语义运行仍是 `not_run`。它是局部宿主工具格式，公共 RecallResult v1、QueryPlan、能力协商和持久化恢复保持独立。

## 使用过程

1. 当前模型使用 `memory_companion_sources` 或 `memory_companion_navigate` 的 event_time/event_context 读取本轮原文。
2. 将已读片段整理为 rows，说明事件身份、主体、现实层、发生状态、目标相关性、歧义、时间和来源引文。
3. 调用 `memory_companion_events(plan)`；程序重验权限、来源版本、逐字引文和本轮读取回执，再按计划计算。
4. 回答时保留冲突、资料缺口与范围含义。已有证据足够的简单问题无需强制调用计算工具。

## 模型与程序的职责

| 字段/动作 | 模型决定 | 程序核对或计算 |
| --- | --- | --- |
| goal / unit / select | 当前问题想找什么；统计单位；主体、现实层及是否实际发生 | 校验类型、支持值和资源上限；按声明筛选 |
| event_key | 哪几条提及属于同一事件，哪些是不同事件 | 相同 key 分组；不同 key 不因同日、同名或文字相似自动合并 |
| relevance / identity / resolution | 是否满足目标、身份是否确定、材料是否有未解矛盾 | uncertain/conflicting 留在 unresolved；确定不符合的放 excluded |
| subject / world / occurrence | 本人/他人/助手、现实/虚构、发生/没发生/计划/取消 | 依 select 计算；不凭引号中的“我”、消息新旧或固定词表替模型做语义判断 |
| supersedes | 是否存在同一事件的明确纠正或撤回；纠正行给出最终解释 | 仅允许同计划同事件引用，拒绝环和缺失目标；旧行/引文保留，不以新消息自动覆盖 |
| time | 是哪条来源所说的何时；只知一天还是确知钟点 | 按来源时区算历史相对日期、时间区间交集、窗口内外和先后偏序 |
| evidence | 哪些原话支持本行解释 | source_ref/version 必须来自本轮已返回片段；重新读原行、核权限和完整 SHA-256 指纹，逐字 quote 必须在已读脱敏片段内 |

程序不核验开放语义是否真实成立。真实引文可以被模型误解，模型也可能错误合并/拆分事件；这些属于真实模型验收，不因 Schema 或引用核对通过就标为事实。description 是模型的受限文本，不解析为命令。历史消息和引文仅是数据，不能当指令执行。

## 时间与计算口径

time 支持 `unknown`、`date`、`relative_day`、`instant`、`interval`。非 unknown 必须引用本行 evidence 的 source_ref。date 提供 YYYY-MM-DD 和 IANA 时区；relative_day 提供整日偏移 days 和时区，以该消息的当地日期为锚点计算，不能拿当前查询日期解释旧消息的“昨天”。无法解析锚点时保留未知。时区来源和词义由模型判断，程序不会自动推断行程时区。

一天表示该时区两次当地午夜间的半开区间，夏令时可能是 23/25 小时；瞬时事件允许起止相同。多个明确属于同一事件的时间约束取交集，交集为空保留冲突，不混合时间。不同当地日期的交集若只覆盖部分一天，精度为 interval，不假称整日。

可选 window 筛选的是**事件时间**，不是消息时间。事件完整落在 `[start,end)` 内才纳入；明确在外的排除，跨边界或时间未知的保留未决。一个区间内的事件可能在区间外才被提及，取数窗口不能自动替代事件覆盖证明。

operation 支持 list/count/latest/earliest/by_day。返回均保留纳入、排除和未决事件以便复核。`aggregate.count` 是按模型解释成立的事件组数，`by_occurrence` 分开实际发生、明确没发生、计划及取消；不能把明确没吃的一天算成实际进食次数。单位由 unit 明示，不是来源条数或现实总数。

latest/earliest 返回已给材料中的时间候选：区间重叠可有多个，同一天无钟点不能挑最后一条聊天冒充最近事件；unknown/未决项使 ordering=unresolved。by_day 将整个时间范围能归入同一当地日期的事件分组，跨日范围和未知时间列 unplaced。`days_without_resolved_events` 只说明给定材料没有已确认条目，不能说现实没发生；by_day 必须有 window，超过 31 天不展开空日网格并明确 day_grid 缺口。

## 来源、预算与返回边界

来源读取回执只在当前轮内存中保存，绑定宿主身份、源版本、Memory/ACL 版本、已返回片段位置与 120 秒到期时间；同版本补读不会延长旧片段期限。未读 ID、旧轮、换人格/用户/Bot、过期、修改/删除/新记录/ACL 变化会拒绝计算。原始来源仍独立核对会话、平台、Bot、人格和参与者。全时间线版本属于保守失效，其他会话新消息也可能触发重查。

计算与取数/导航共用默认 3 步（配置上限 8），不增加后台模型调用；需要计算时应预留一步。单计划最多 48 行、96 个不同来源、每行至多 6 条引文、UTF-8 编码 48000 字节。它们是资源预算，不是确定同一事件或写入习惯的次数门槛。重复同计划不能靠重调重置预算，换计划同样占一步。

查询重读至多 96 个本轮已见来源，异步取消向上传播，不保证同步 SQLite 线程立刻结束。当前尚无独立计算墙钟 deadline；源码/权限使用前后检查，不提供跨进程快照。source_version 改用完整原文/元数据的 SHA-256，覆盖后半段和大小写；不等于事实 revision 或历史版本恢复。

coverage 由程序生成：本次引用数、当前版本已读但未引用数、取数查询/窗口/是否还有页，以及语义覆盖未建立。只报告仍在有效期且版本一致的读取记录，不回显其他来源 ID。`event_coverage=not_established` 和 `semantics=model_interpretation_not_verified_by_program` 固定保留。最后一页不等于语义全集。`rejected` 清空结果，已消耗步骤不会退还，也不会把无权与不存在细分给模型。

宿主 initialize 将完整嵌套 request Schema 绑定到该插件自己的工具；装饰器的 object 描述不足以表达行内字段。绑定保留原工具 handler/权限和激活状态，不新建外部数据库入口。服务端独立验证参数、时间、来源、纠正图和预算；Schema 不能证明授权或语义正确。

下一项为模型自主取证的隔离端到端验收，按用户反馈优先[胖次话题的完整问答](../../../../../astrbot_plugin_private_companion/docs/MEMORY_COUNTEREXAMPLE_EVAL_V0.md#frequent-topic-recall)：上次询问日期、对应回答、改口/跨日和一周问答。回答可能只含属性而没有话题词，需要展开来源并确认指向；只找到问题不补造回答。简单问题证据足够就直接回答，必要时才计算日期先后或次数。既有早餐夹具保留为通用计算验证；同一资料/预算下记录实际查询、未读范围、最终引用、错误断言、模型调用/token 和延迟。公共能力协商、受限多步计划、大范围续跑及捕获补偿仍待补齐。

21:40 的[自然聊天反例](../../../../../astrbot_plugin_private_companion/docs/evaluations/S3_RECALL_QUERY_DRIFT_20260913.md)已出现日期失败，但日志未见本工具或来源工具执行，不能计为事件计算验收。首轮查询扩展与补查提示已修复，下一次需先核对实际请求工具和模型补查，再判最终答案；更早同句不能替代目标日期，用户外部截图与库内原文分别记录。该次 83.512 秒为消息接收到准备发语音的整条链路，不能归为事件计算耗时。

后续[隔离模型六例](../../../../../astrbot_plugin_private_companion/docs/evaluations/S3_RECALL_MODEL_20260913.md)已实际自主调用 sources/recall，最终简短原则提示下取得主要答案依据，仍有查询效率问题。模型未选择 events，这些小规模问答不能计为本计算工具已实际验收，也不强制为拿到调用次数而让简单问题计算一次。
