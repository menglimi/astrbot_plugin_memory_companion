# 记忆参考适配器设计 v0

> 导航：[Memory 设计目录](./README.md) / [设计总纲](../../astrbot_plugin_private_companion/docs/FRAMEWORK_DESIGN.md) / [主题目录](../../astrbot_plugin_private_companion/docs/FRAMEWORK_DESIGN_INDEX.md)。定位：Memory 本地实施主稿；负责现有代码到公共能力的映射，不重新定义公共字段、全局阶段或验收结论。

> 状态快照：2026-10-08。本地只读、反思、纠正、查询及来源捕获均有分批证据，A/B/C2a 的历史加载记录不代替本次发布的生产验收。C2b context 范围优化、C2c 语义维护/来源发现/v3 绑定和 C3 范围批读基础已局部实现；语义与批读默认关闭。真实 Provider、完整 memory.api、共同资源/回放、标准订阅、可信历史恢复和非空完整重启仍未验收，当前排期统一见路线看板。

09-12 实现记录（只说明该批证据）：`read_user_memory_summary` 透传实际数据库 `retrieval_revision` 并排除已失效记录；`lookup_bot_personal_archive` 沿用写入的生产方 capability 和命名空间校验，只返回回执；Bot Personal 的版本检查和更新已进入同一 SQLite 事务。真实 Memory bridge、临时数据库重开、回执丢失和并发修正测试已通过，详见[本轮验证记录](../../astrbot_plugin_private_companion/docs/evaluations/S3_MEMORY_RECOVERY_20260912.md)。这部分证据为 `R`，未重载实际 AstrBot，也未实现下文标准 ProposalReceipt、memory.changed outbox 和完整订阅恢复，不能替代 §4.3 的提交保证。

本稿说明 `remember_you` 如何成为新框架首个 Memory Service 参考提供方。公共字段见[记忆外部接口](../../astrbot_plugin_private_companion/docs/MEMORY_PROPOSAL_QUERY_CONTRACT_V0.md)，注册、绑定、调用与卸载见[外部插件生命周期](../../astrbot_plugin_private_companion/docs/COMPANION_EXTENSION_LIFECYCLE_V0.md)。领域适配不复制公共协议。

## 0. 本稿怎样使用

| 要找的内容 | 位置 | 边界 |
| --- | --- | --- |
| 身份、owner 与旧命名空间 | §1、§4.4 | 只定义可无损映射条件，不以目录名或旧 key 补造授权 |
| 现有写入、查询和回执映射 | §2--§4 | 记录代码事实与目标接口之间的差距 |
| A/B/C2a 及 C2b--C4 接点 | §4.2.1--§4.2.5 | 查询路线由公共 A/B/C 专题决定，本稿只落到本仓库代码 |
| CAP 原文可靠性接点 | §4.3.1 | 来源保存、补偿、恢复和消费需整链启用 |
| 生命周期与能力覆盖 | §5--§6 | `redesigned` 表示设计状态，不表示生产 ready |
| 当前实施与验收顺序 | §7 | 具体进度和证据数字仍以路线看板为准 |

正文中的日期化段落保留当时接线事实，不能单独作为最新状态。新增实现先更新对应接点；只有阶段、加载或验收证据改变时，才同步路线看板和日期化报告。

2026-09-12 新增局部语义纠正：`correct_user_memory` 支持当前本人私聊的常见事实/画像 inspect、correct、lookup；旧版本归档、新版本与修订回执同事务保存，画像同步取值及方向。`check_memory_dependencies` 批量核对逐条语义版本，注入字符串附带实际展开的 id/version，召回缓存拒绝旧版本。Private 的活动工具和正常开发主动路径已消费这些引用。Memory 77 项针对性检查通过，测试证据仍为 `R`，详见[语义纠正接线记录](../../astrbot_plugin_private_companion/docs/evaluations/S3_MEMORY_CORRECTION_WIRING_20260912.md)。同日稍后已实际重载 Memory 与 Private，新方法已声明、工具已注册，新增局部 `H` 证据见[宿主重载记录](../../astrbot_plugin_private_companion/docs/evaluations/S3_HOST_RELOAD_20260912.md)。生产纠正回执检查时为 0；真实模型纠正、独立摘要/承诺/日程结构、标准订阅及完整宿主重启仍未验收。

## 1. 身份与适配边界

2026-09-13 补充：真实 Provider 与默认模型已完成[隔离纠正/查账/活动恢复用例](../../astrbot_plugin_private_companion/docs/evaluations/S3_MEMORY_MODEL_20260913.md)，并据实际失败修正活动参数反馈和纠正语义提示词。模型验证仍使用 fixture 身份、P5 授权和限定候选，不能替代本节真实身份映射、生产检索及完整进程恢复。

仓库目录为 `astrbot_plugin_remember_you`，当前 [metadata.yaml](../metadata.yaml) 的插件 ID 为 `astrbot_plugin_memory_companion`。注册使用宿主确认的插件 ID，provider 标识与 manifest 一致；目录名仅用于定位源码，不能充当授权主体或稳定数据 owner。

目标适配链：

```text
external caller -> Runtime scope/authorization/binding
                -> Memory capability adapter
                -> domain use case + authorized store context
                -> existing Memory-owned storage/indexes
                -> receipt / AnswerEvidence / change event
```

适配器只负责类型转换、用例选择和回执映射。领域事务、原始证据和索引由 Memory 所有；核心不接管数据库。模型判断、类型归因和冲突解释沿用已有语义产物或按显式预算生成，不为字段转换额外调用 LLM。

## 2. 当前代码事实

以下是本轮只读检查的入口，不代表它们已经满足标准能力所有要求：

| 入口 | 已有能力 | 新契约需验证/补齐 |
| --- | --- | --- |
| [main.py](../main.py) 的 initialize/terminate | 启动维护 dispatcher；关闭 bridge 后等待 service.aclose | 接入共享 Supervisor、provider_generation 和逐阶段 shutdown 回执；避免重复启动任务 |
| [core/bridge.py](../core/bridge.py) 的 remember/recall | 将 event、content、note_type 或 query 交给 service；存在 active/probe 和 namespace 入口 | 外部 DTO 不传 event；区分新协议绑定与原私有生产者授权上下文 |
| [core/memory_proposal.py](../core/memory_proposal.py) | 同名 MemoryProposal 支持文本、durability、有效期、置信度与来源字符串 | 与新 wire DTO 区分；缺少标准 subject/predicate/qualifiers、owner 与 revision 请求语义 |
| [core/service.py](../core/service.py) 的 tool_remember | 从真实 event 解析 SessionContext，创建 MemoryRecord，返回 memory_id/状态 | 需要不依赖 event 的授权用例入口，以及事务回执、幂等与来源解析；不能只改返回字段 |
| service.search/search_context_slots | 有 SessionContext、生命周期过滤、候选分槽、缓存重验和诊断 | 检查完整 RuntimeScope、用途和 namespace 映射；返回真实 AnswerEvidence，复核过滤预算 |
| [core/store.py](../core/store.py) 的 insert_memory | 已有数据库操作恢复、内部事务和内容去重/合并 | 内容 fingerprint 不等于调用幂等键；需要明确单次提交、revision、回执/outbox 原子性 |
| [core/scoped_store.py](../core/scoped_store.py) 的 ScopedStore | namespace/purpose 校验、revision 连续性、event 去重、epoch 状态 | 复用隔离基础；现有操作按 event_id + migration_epoch 去重，与跨 runtime generation 的逻辑幂等不是同一语义 |

现有 ScopedStore 是 REQ-041 数据通道，不能绕过其 NamespaceContext、AssurancePolicy 或 migration_epoch。runtime generation、迁移 epoch 和 memory revision 分别描述实例、数据交接与事实变化，适配器必须分别传递，不能把它们合成一个新版本号。

## 3. 能力映射和可用性

| 目标能力 | 适配用例 | 就绪条件 | 条件未满足时 |
| --- | --- | --- | --- |
| memory.proposal.submit | validate proposal -> authorized mutation -> durable ProposalReceipt | add/correct/retract/no_op 的语义均满足 schema；证据、作用域、revision、幂等回执可验证 | 不注册为完整 v1 Writer；影子验证或 unavailable/contract_not_ready |
| memory.query | authorized query -> retrieval -> evidence projection | 作用域与过滤完整映射，最终片段有真实证据；不支持的必需查询语义可明确拒绝 | 相关能力 unavailable，不能降级成更宽搜索 |
| memory.operation.get | owner 账本查询 | 用 operation_id 或原 caller/owner/幂等键查询；可辨已提交、未提交与未知 | 不以“查不到 memory_id”代替 not_committed |
| memory.changed | owner outbox -> authorized EventBus | 与事实同事务，订阅可恢复并能传播撤回 | 不从轮询列表变化伪造可靠变更事件 |

上表是目标能力清单。只实现 add 的适配器不能声明完整 proposal.v1 后把 correct/retract 当作可选；需要保持未就绪或另行评审一个独立的受限能力版本。类型和检索策略的可选 features 则按公共协议协商。

记忆消费者可按自己需要绑定 query，不要求必须安装外部提议来源；Writer 提供方缺失或降级不会阻塞普通回复。完整 Memory 提供方验收须覆盖四项能力，单项只读验证不能宣称完成整条闭环。

## 4. 从旧入口到标准用例

### 4.1 写入

新路径消费 Runtime 已解析的调用上下文，通过 Memory 内部转换建立授权 SessionContext/NamespaceContext。身份、Bot、人格、用户/群和可见范围无法无损映射时返回 scope_required；不构造假的 AstrBot event，不从裸用户 ID 推算旧 namespace。

旧 tool_remember(event, ...) 留在真实宿主 hook 边界。未来可以把两条入口共同需要的领域操作提取为受限用例，内部参数由已授权上下文提供。没有完成拆分与契约验收前，不用外部 DTO 直接调用需要 event 的旧函数。

| 标准字段 | 旧材料可复用部分 | 适配处理 |
| --- | --- | --- |
| subject/predicate/object/qualifiers/attribution | MemoryRecord 的实体、content、metadata 和关系字段 | 保留真实主体和限定条件，不把所有事实都变成 Bot 对当前用户的陈述 |
| evidence_refs | 真实消息证据、来源引用和必要摘要 | 从授权来源解析并保存出处/revision；字符串引用或 ctx.message_text 不自动证明所有断言 |
| retention | durability 与有效期 | 用具名兼容策略转换并返回 policy_revision/实际保留期；pinned 只申请 protected |
| types/extensions | memory_type、metadata | 未识别可选类型保留通用断言及元数据；必需扩展不支持则拒绝，不能映射成固定 other 丢失语义 |
| idempotency_key | scoped event 去重、旧 stable_id/fingerprint | 逻辑请求账本绑定 caller/owner/能力主版本，独立于内容去重和 runtime generation |
| expected_revision | ScopedStore revision/冲突能力 | 由 owner 原子校验，不能调用前读一次版本再无条件写入 |

旧 MemoryProposal 的 requested_persistence=false 转成 no_op，返回 succeeded + skipped，无事实记录。旧工具返回 `ok=false,state=skipped` 不应笼统映射为 failed；普通异常也不能一律宣称未提交。低置信度策略可复用但记录版本，0.55 不成为新外部协议的固定分类阈值。

### 4.2 查询

优先复用 service.search/search_context_slots 的领域流程，调用方传入已授权上下文，不能设置 admin_read_all 来跳过权限。旧 event/P5 证明若仍是某个读取路径的必要条件，必须由受信适配层提供有效证明；没有合法等价映射就保持该能力不可用。

查询转换必须逐项处理 namespace、purpose、types、subjects、时间范围、历史/当前冲突策略、pending、预算和 cursor。旧 top_k 不能代替总 token/字符预算，旧返回 memories 不等于最终注入证据。保留 cache 重验，并加入新请求要求的授权、数据与描述符 revision；返回前再次检查撤回、来源状态和完整事实。

AnswerEvidence 的 atom_id/revision 必须来自权威对象，不能给所有旧记录临时填 revision=1。归属或证据不完整的旧数据可提供注明缺口的受限兼容投影，不在后台凭摘要补造事实。部分检索失败可返回 partial 与 coverage，条件不支持不得默默丢弃过滤。

<a id="adaptive-query-adaptation"></a>

#### 4.2.1 复杂召回路线的接入决定（2026-09-13）

技术方向已收敛到[记忆领域 §7](../../astrbot_plugin_private_companion/docs/MEMORY_CONTRACT_V0.md#adaptive-memory-query)：当前模型按需规划，Memory 执行通用操作，复用事件时间线、全文/向量候选与来源分页。公共 profile 与通用计划仍为设计；2026-09-13 已增加回执核验、按引用读原文、独立原文查询，以及模型给定事件后的引用重验/分组/统计；本地来源与事件成对格式已形成，不代表模型语义、集合覆盖或全部历史查询已经验收。

| 现有位置 | 优先复用 | 进入复杂查询前需要补齐 |
| --- | --- | --- |
| service.search/search_context_slots、core/retrieval.py | 授权上下文、全文/向量、时间候选、重排与缓存重验 | 区分相关查找与范围枚举；RRF 先作同预算对照，不能将当前 top_k、重要度或现有排名当成穷尽读取 |
| core/time_intent.py | 时间对象与日期运算能力 | 意图来自模型结构化计划，时间锚点、来源时区、精度和区间口径显式化；现有词面分支与固定默认时区不能宣称支持 MRQ 全部时间语义 |
| service.tool_navigate / tool_sources 与来源存储 | 引用导航与独立原文 search/range/context/read；FTS5 trigram 或授权分区子串查询、稳定时间分页、版本绑定 cursor 和长消息补读；本地成对 Schema | 公共能力协商、跨会话/旧人格归属和更大范围预算；现有词句匹配与最后一页不证明语义查全 |
| service.tool_events / core/event_query.py | 本轮受信片段、完整来源指纹重验、模型声明的事件分组、时间/排序/计数/按天整理；同轮预算与未决项 | 验证模型自主取证/消歧/纠正解释及最终答案，单独测 token 与延迟；局部 plan 不冒充通用依赖计划 |
| core/memory_revision.py 与 owner 修订接口 | 实际版本、失效记录、纠正和使用前核对；临时事件随来源/权限版本变化拒绝旧依据 | 公共查询结果缓存仍需完整绑定条件及新增相关事件，不能只核对已选 ID；全局保守失效的细化需另验边界 |
| Memory bridge 与外部 capability adapter | Runtime 身份映射、能力协商和现有回执 | 按[接口 §5.1](../../astrbot_plugin_private_companion/docs/MEMORY_PROPOSAL_QUERY_CONTRACT_V0.md#planned-query-compatibility)新增成对查询 profile；区分源消息、临时判断、真实 pending 与事实，不伪造 MemoryAtom |

模型规划在当前对话中按需发生；Memory 内部执行器不自动启动另一个规划模型或定时巡视。语义整理可由当前模型批量消费工具结果完成，后台无当前模型时显式绑定语义提供方并共用请求预算。查询产生的临时判断不会自动提交事实，索引和访问计量保留为派生运行记录。

实施顺序使用 [S3-MQ-01--03、S5-MQ-01、S6-MQ-01](../../astrbot_plugin_private_companion/docs/FRAMEWORK_ROADMAP_AND_STATUS_V1.md#memory-query-roadmap)。先实现支持的精确语义，旧路径只能承接可无损映射的子请求；遇到不支持的必要操作或来源能力，明确降级，不把约束直接丢掉。

当前来源读取不调用 `_timeline_row_as_memory(ctx, row)` 为未知记录制造归属，而是独立核对原行的会话、平台、参与者、Bot 和人格；原文继续脱敏。`source_coverage` 的不可用合并不存在/无权，不向模型暴露隐藏记录。源版本指纹不是 MemoryAtom revision，摘要 `occurred_at` 与消息 `message_at` 也不自动升级为事件发生时间。字段边界和下一步见[领域 §7.3](../../astrbot_plugin_private_companion/docs/MEMORY_CONTRACT_V0.md#73-数据基础能追溯经历也能知道哪里没记录)。

局部 [source-query profile](./contracts/source-query/v1/README.md) 只供当前宿主工具消费，不经公共 RecallResult v1。查询不增加内部模型调用、事实写入或后台巡视；模型自主选择查询与换词，消费结果仍会占用模型往返。该包 100 项相关测试通过（新增 52），涵盖实际结果 Schema、授权分页、UTC 跨日、修改/删除/ACL 导致游标失效、取消和 SQL 限时、FTS 重建；证据见[原文查询记录](../../astrbot_plugin_private_companion/docs/evaluations/S3_SOURCE_QUERY_PAGING_20260913.md)。

后续 [event-query profile](./contracts/event-query/v1/README.md) 已接通临时事件和带来源计算，新增 52 项检查通过；本轮定向集合去重 152 项，分次运行明细及宿主证据见[临时事件记录](../../astrbot_plugin_private_companion/docs/evaluations/S3_EVENT_QUERY_20260913.md)，不与前包累加为全局测试数。原文/导航实际返回后才签发本轮读取回执，计算核对引文所在片段、当前来源与权限；不从摘要自动确立事件时间，不提交事实或 pending。下一步验证真实模型从自然问题自主查证、处理歧义到回答的全过程，并在相同预算下比较正确性、token 和延迟。

21:40 的[第二组自然聊天失败](../../astrbot_plugin_private_companion/docs/evaluations/S3_RECALL_QUERY_DRIFT_20260913.md)表明，工具已加载仍可能没有补查：完整回忆问题被近期天气内容带偏，注入没有目标依据，回答却猜了月份。现已删除“回忆问题抽词少就扩展”的分支，保留现有低信息/指代追问机制；当前请求历史传入 compose，提示模型缺证据时自主补查、核对对应问答和日期，新增 Memory 钩子处请求工具诊断。57 项定向检查通过（新增 8），修复后真实模型效果未验。热重载发生原生崩溃后已恢复宿主，两插件启用、Private ready、新提示可见；该次不计热重载成功或受控恢复验收，历史测试数不累计。

22:53 后续：已完成[首组真实模型隔离问答](../../astrbot_plugin_private_companion/docs/evaluations/S3_RECALL_MODEL_20260913.md)。最终简短说明让模型自主判断补查、理解问答/更正和表达不确定，不依赖词面识别覆盖每个问法；不固定句式或查询顺序。五类历史问题的主要答案有依据、寒暄不查询，仍有多余调用与一次共享预算拒绝。最终提示尚未加载线上，生产效果、完整 MRQ 和模型事件计算继续待验。

2026-09-14：[查询进度及关联](../../astrbot_plugin_private_companion/docs/MEMORY_QUERY_SESSION_DESIGN_V0.md)的 A 与 B1/B2 已有局部 C/R，分别使用 [v1](./contracts/query-session/v1/README.md) 和 [v2](./contracts/query-session/v2/README.md) 成对格式。默认保留四个原查询工具；sources 在当前请求启用 B 时可携带便笺并返回 v2，其它原工具保留 A，service 兼容入口保持原类型。`memory_companion_query` 只投影 status，B 增加按 ID 回看。B3 对照已运行但自主便笺使用/收益未观察到；C1 基线及 C2a 授权向量路线局部 R 完成，下一 C2b。A/B/C2a 未加载生产，公共复杂查询能力仍未就绪。

| 现有代码 | A 包实现与后续边界 |
| --- | --- |
| core/service.py 与 core/query_session.py | 复用 `_reconstruction_states`、锁和预算，登记 operation ID、参数、实际结果、失败和取消；ContextVar 绑定在途工作。实例代际参与轮次键，同一实际操作只执行/登记一次 |
| core/source_evidence.py 的 `record_source_read` | 复用已签发来源、版本、片段和期限，增加可知文本长度以求首个未读偏移；旧返回记录不证明语义正确或当前原文仍在模型上下文 |
| core/source_query.py 与 core/event_query.py | 复用已解析身份，事件计算只复制所需回执；保留原 owner 结果和错误，在独立封套中附进度，sources/events v1 内层保持原义。失败 usage 缺失保持未知，预留如实记录 |
| core/store.py 的 `query_progress_revisions` | 一次 SQL 核对来源/检索版本元数据；状态查询不重检索正文、不续期，已成功消费页不会因历史裁剪重新显示为可续 |
| core/continuity.py 的当前轮快照与内部 QueryPlan | 作为当前问题/已有上下文的接入线索；B 再明确压缩后原文是否仍可读，不把现有内部样板宣称为通用计划或恢复器 |

A 如实显示 sources/navigate/events 默认共享 3 步；普通 recall 每次最多 10 条候选，**没有独立次数预算**，调用数只作观测。Host 总模型/token 预算尚未接入；统一预留/结算与重复工作复用留到 C。来源/cursor 的 120 秒期限与状态约 600 秒清理分开；短进度最多 900 字符，详细状态按需查看，同轮历史有界。没有固定查询顺序或额外摘要模型，跨轮/跨重启恢复另排。相关测试分次去重 150 项通过（新增 23），40 组小库对照额外耗时中位数约 1 毫秒；模型日期例有补充月份错误，一周题仍多一步，见[验证记录](../../astrbot_plugin_private_companion/docs/evaluations/S3_QUERY_PROGRESS_20260914.md)，不据此宣布总体提速或生产效果通过。

2026-09-14 [B 设计](../../astrbot_plugin_private_companion/docs/MEMORY_QUERY_SESSION_DESIGN_V0.md#query-relation-package-b)已完成下列本地接线和边界验证，新增独立 v2，现有 v1 格式保留：

| 接入点 | B 的当前改动 | 边界 |
| --- | --- | --- |
| main.py 的原生 sources handler 与请求投影 | 已接可选 `query_note`，原查询参数照常传 owner；当前请求单独绑定 query-session v2，已有 status 可按便笺 ID 回看 | 原名称保留，仅 sources 声明便笺 Schema；开关、绑定、handler 均支持才提供，关闭回到 A，原生及 partial handler 隔离检查通过 |
| query_for_model / query_session | 协调原查询与便笺独立回执；复用同轮状态，补便笺自身修订、替换及失效索引 | 原 service 入口仍是 v1，实际查询不重复执行；语义判断只标模型声明，不提交 Memory 事实 |
| source_evidence / store 的版本元数据 | 绑定此前实际返回的来源、版本、片段和原期限；利用已有核对结果校验便笺，不重检索全文 | 引用有效不证明语义正确；依据失效后不重发便笺正文，不通过编辑或重试续期 |
| continuity / Host 请求可见性 | B2 已核对实际工具循环：先压缩再直接请求 provider，插件无压缩后最终请求入口 | 保持 unknown + 按需 status；实际压缩器夹具验证回看与原句补读，不计生产 H 或自动恢复 |

B1/B2 局部接线和 B3 对照已完成，见[独立记录](../../astrbot_plugin_private_companion/docs/evaluations/S3_QUERY_RELATION_20260914.md)：相关集合分次去重 173 项通过，新便笺 23 项；40 组本地便笺额外中位数 0.456 ms。24 样本/64 请求/56 工具均未提交或回看便笺，收益未证。后续 C1 已完成下列结构基线；B 自主使用、Host 可靠加载和生产仍各自待验。

2026-09-14 [C1 基线](../../astrbot_plugin_private_companion/docs/evaluations/S3_QUERY_SCALE_20260914.md)及后续 [C2a 实现](../../astrbot_plugin_private_companion/docs/evaluations/S3_VECTOR_SEARCH_C2A_20260914.md)已有局部 R；C2a 改了运行时源码但未加载，真实模型为 0。C 的[细化设计](../../astrbot_plugin_private_companion/docs/MEMORY_QUERY_SESSION_DESIGN_V0.md#query-scale-package-c)对应如下接入点。C2b 细化设计 D 和 SQL 选型探针已完成；2026-10-08 在 v1 context 路径补入等价时间范围条件，并通过同时间戳分页及实际索引计划定向回归。双字索引、独立维护和 v2/v3 成对绑定，以及 C2c/C3/C4 验收仍待推进：

| 接入点 | 已发现的限制 | 接下来实现与验收 |
| --- | --- | --- |
| RetrievalEngine._embedding_candidate_memories / MemoryStore.search_memory_embeddings / vector_search | C1 旧路径先取全局 1200 条，旧合法目标可被其它会话挤出 | C2a 已接入授权/生命周期集合内精确分块比较，按 ID/版本回少量原记录；92 项测试/新 16 及 10 组最终数值对照通过。首查、持续更新、真实 embedding/宿主待验；不依赖 FAISS |
| MemoryStore._query_source_page_sync / timeline_source_fts | trigram 不支持两字词入口，混入短词整条路线退扫描；context 的 tuple 原先未用于时间范围定位 | context 已在 tuple 边界外增加等价 julianday 条件，保留完整 tuple；双字符 FTS5 候选、dirty/缺覆盖补查、实际分页/权限/维护与成本仍待验 |
| timeline 来源和异步索引维护 | 短回答/后来更正不一定有提问关键词；派生索引需要独立维护和授权重验 | [C2c 接点](#source-semantic-c2c-adaptation)：已实现片段/邻近窗口、dirty 依赖、后台建库、授权候选融合与回读、query-session v3 绑定；默认关闭，真实 Provider 和语义收益待验 |
| query_session / source_query / source_evidence / query_notes | 原导航仍共用步骤、精确重试拒绝；无关会话写入使全局来源及便笺失效 | [C3 接点](#query-range-c3-adaptation)：已实现范围批读、UTF-8 owner 预算和正文连续偏移；共同资源、精确回放、分区变更与整链有效性仍待实现 |
| scripts/benchmark_query_scale.py 与后续模型 runner | 180 次脚本路线/270 sources、6 已知向量探针，只证明结构与成本 | [C4 验收接点 D](#query-model-c4-adaptation)：未见资产、同预算/真实模型、全答案与实质回答等待；先知及大预算对照单列，新 Runner 未实现 |

<a id="source-query-c2b-adaptation"></a>

#### 4.2.2 C2b 的实现接点（D，2026-09-14）

主决定见[短词与时间定位设计](../../astrbot_plugin_private_companion/docs/MEMORY_QUERY_SESSION_DESIGN_V0.md#source-query-c2b-design)，版本见[接口绑定设计](../../astrbot_plugin_private_companion/docs/MEMORY_PROPOSAL_QUERY_CONTRACT_V0.md#source-query-c2b-compatibility)。目标是让“搜两字词、查看那句话前后的消息”少读无关历史；语义关联仍交给当前模型，正常查询不增加模型往返。2026-10-08 基线核对确认当前 FTS 由 timeline 写事务触发增改删、初始化时重建；source-query v1 仅在所有词项长度均至少 3 时选 trigram，其余在授权分区做原 `instr(lower(...))` 匹配，尚无双字索引、dirty/缺覆盖并查或混合候选合并。context 时间范围定位已有局部实现和定向回归；完整基线审阅及未覆盖项见[审阅记录](./evaluations/source-query-c2b-baseline-review-20261008.md)。该核对及现有 75 项交叉测试不构成 C2b 整包 SQB/性能验收。

| 顺序 / 接点 | 实现责任与退出条件 |
| --- | --- |
| 1. core/store.py 的 _query_source_page_sync | context 前后查询已在 tuple 边界外补 julianday 等价 `<=/>=` 条件；同时间戳双向分页及实际索引范围计划已做定向回归。原排序、完整 tuple、权限保持不变；search/range 续页尚未扩展该优化，单独交付沿用 source_context |
| 2. 拟新增的来源词法索引模块及 store 内部表 | 使用独立整数 docid 映射稳定 source ID；Unicode 相邻双字符编码到 FTS5，保留长词 trigram。授权后合并各分支、dirty/缺覆盖字面查询，原 instr 核对后统一去重/排序/lookahead，无全库先截候选 |
| 3. store 的原写事务与 Memory 本地维护生命周期 | SQL 触发器标记增改删/归属/ID 变化，不依赖 Python UDF；维护任务分批回填、提交时重验变更序号，再清理对应 dirty。取消/关闭收束在途 SQL；缺能力、只读、积压或未证明完整时回原路径，不在首查同步全量构建 |
| 4. source_query / service / main 的当前请求绑定 | 拟新增 source-query v2 和 query-session v3 成对包；同一请求的工具投影、handler 和 serializer 选定一致版本。旧 direct 和 A/B 原入口保持现有类型，部分能力未就绪时回完整旧接法；来源操作与预算仅执行/登记一次 |
| 5. query_session / source_evidence / query_notes / event_query | 延续真实来源、片段、版本、原期限和作用域；v3 按 operation 核验内层 profile，便笺开关继续控制可见字段。新词法候选不认证事件全集、问答关系或便笺语义 |

只有以上实际链路通过[12 组 SQB 场景](../../astrbot_plugin_private_companion/docs/MEMORY_COUNTEREXAMPLE_EVAL_V0.md#source-query-c2b-evaluation)，才能分别登记局部 C/R。目前这些场景均为 not_run；[SQL 设计探针](./evaluations/source-query-plans-design-20260914.json)只核对合成内存库的计划、编码及 FTS 能力，不能当作工具或生产验收。实现对照还须记录索引构建、写入 P95、dirty 积压、磁盘/WAL/RSS、锁等待和总查询成本；真实模型效果归 C4。

<a id="source-semantic-c2c-adaptation"></a>

#### 4.2.3 C2c 原文语义的实现接点（D，2026-09-14）

主决定见[原文语义专题](../../astrbot_plugin_private_companion/docs/MEMORY_QUERY_SESSION_DESIGN_V0.md#source-semantic-c2c-design)，字段和组合绑定见[接口设计](../../astrbot_plugin_private_companion/docs/MEMORY_PROPOSAL_QUERY_CONTRACT_V0.md#source-semantic-c2c-interface)。当前实际 embedding 针对 MemoryRecord；不会因已有向量召回就自动支持 timeline 原文。本次仅查源码并细化设计，未生成文档向量、改运行逻辑或增加本地契约包。

2026-10-08 按路线看板在 C2b 基线审查后开始 C2c-1：新增 [core/source_semantic.py](../core/source_semantic.py)，建立 generation 配置/状态、无正文副本的片段与窗口文档元数据、逐来源反向依赖和按 generation 独立合并的 semantic dirty。后续已补历史扫描 checkpoint、可暂停恢复的 embedding worker、窗口构建、来源发现/融合/真实回读与 query-session v3 绑定。来源更新/删除会在同一事务中将直接依赖标为 stale；提交前重验源版本、权限和代次。未注册活动 generation 时来源写入不会增加 semantic dirty。语义路径和历史回填默认关闭；实现及替身测试不证明真实 embedding 或 C2c 整包通过。

| 接入点 | 可复用部分 | C2c 须补的责任 |
| --- | --- | --- |
| service._serialize_navigation_source / injection 脱敏 | 来源角色、真实时间、source_version、可读正文及 offset；source_evidence 的实际已读片段回执 | 先脱敏再分片，窗口各片段各自保留引用；实际回读后才签发。脱敏版本变化须失效索引/来源回执/便笺，现 source_version hash 不含处理版本，不可只靠 hash |
| source_partition / source_visible | 现有私聊/群、Bot、人格及原行授权条件 | 每个窗口依赖在排名前符合当前可读范围；条件未知不补造旧归属。来源权限独立于 MemoryRecord，不能套其 pending/共享策略 |
| vector_search 的 block_scores/数值校验思路 | NumPy 或标准库分块余弦、稳定排序、取消检查与有界数值缓存 | 来源 ID/span/generation 适配和授权后按来源归并各视图，再 top-k；缓存纳入全 Memory 总预算，原 search_embeddings_sync 不直接接 timeline |
| retrieval._reciprocal_rank_scores / C2b 字面取数 | 来源级名次融合的通用数学思路；字面 OR 和授权查询 | 单片段/窗口先归并为一个语义分支，模型 terms 为可选另一分支；不能复用 sources 最新时间页冒充全域词法相关排名，也不增加抽词 LLM |
| service 的 embedding Provider / 用量和后台任务 | 已有异步调用、用量记录、任务追踪与前台优先的基础 | 单独适配 query/document 模式、实际模型修订、输入 token/长度及批量响应。旧 _embed_text_with_provider 会按记忆上限截断，不能直接送来源窗口；先绑定允许处理原文的 provider，不自动遍历另一个提供方 |
| store 来源变更 / core/source_semantic.py | SQLite 原写事务、稳定 source ID、source revision；本地已有 Unicode code-point 分片、版本化文档元数据、窗口依赖引用、旧/新归属及时间位置、独立 semantic dirty 和精确序号确认 | 后续实现历史基线扫描与 checkpoint、受授权正文读取/窗口构造、反向依赖失效与邻接变化重建、后台 embedding 和提交前源版本/代次复核；词法 dirty 不与语义 dirty 共用确认。当前还没有查询时排除失效窗口的检索端 |
| main / service / query_session / query_notes / event_query | 当前请求工具投影、同轮预算、来源回执、可选便笺和带来源计算 | 新 discover + source-discovery v1，扩展尚未交付的 query-session v3 的 discover 绑定；旧包不改义。真实返回的上下文占来源额度，实际 provider 消费另记，排名候选无全量时间游标 |

开发依次验文档/依赖、维护、候选数学及授权、回读打包、成对工具链，再使用真实 embedding 与未见自然问法。当前已完成上述本地结构和工具接线，真实 Provider 与语义收益待验。SQS 对照要求在[SQS-01--16](../../astrbot_plugin_private_companion/docs/MEMORY_COUNTEREXAMPLE_EVAL_V0.md#source-semantic-c2c-evaluation)，正式验收仍全部 not_run。真实语义收益和端到端等待不能由 C2a 合成数值或 C2b SQL 探针代替；后台原文回填量、请求费用和前台等待须单独报告。

<a id="query-range-c3-adaptation"></a>

#### 4.2.4 C3 范围、共同资源和分区回执的接入（D，2026-09-14）

2026-10-08 本地交付范围批读基础：[source-query v2](./contracts/source-query/v2/README.md) 的 `range_batch` 采用授权正序 SQL、真实 offset 和 owner UTF-8 字节上限，按请求绑定 query-session v3。旧导航步数与两个全局版本继续生效。共同 lease、执行/输出总账、精确回放和 scoped validity 尚未实现；当前局部 R 不替代完整 SQR 验收。

主方案见[范围与续查](../../astrbot_plugin_private_companion/docs/MEMORY_QUERY_SESSION_DESIGN_V0.md#query-range-c3-design)，格式见[接口决定](../../astrbot_plugin_private_companion/docs/MEMORY_PROPOSAL_QUERY_CONTRACT_V0.md#query-range-c3-interface)。`_reserve_reconstruction_step` 的签名拒绝/三步限制、旧 `query_source_page` 的十二条上限和进度/便笺的全局版本比较继续保留。新 `query_source_range_batch` 独立执行范围批读；C3 其余责任按下表继续推进。

| 顺序 / 现有位置 | 优先复用与实际要补的部分 |
| --- | --- |
| 1. service 的轮次键、预留方法及 query_session._CALL | 保留受信身份/实例/轮次，新增 lease 与 work/invocation 的原子预留和结算；ContextVar 验证 active 不能跨结束父工作继续用。旧入口同轮也记共同账本，关闭显示不关闭计量 |
| 2. source_query_v2 / store.query_source_range_batch | 已交付 range_batch；单事务有界 SQL 块、正序键和当前行 offset，按实际 UTF-8 owner 体积打包。旧 range/limit 保持原义；继续使用 global 版本，完整共同预算及 SQR 验收另补 |
| 3. source_evidence / query_progress / query_notes | 覆盖分遍历/展示/理解；真实 span 和连续页链去重，有界保存缺口，lookahead 不算已读。范围与便笺原期限保留，失效/裁剪不会复活旧 cursor 或回退累计消耗 |
| 4. 共同 owner 入口的只读执行 | 同轮精确指纹、在途合并及有界结果回放；缓存的是读取结果，当前进度和本次 query_note 独立计算。每次输出仍计体积，一个等待者取消不取消其它人，回放不重复推进页链 |
| 5. store 的 source_query_revision 触发器和版本读取 | 拟新增归属分区 revision/generation，原写事务覆盖旧/新归属、空分区首次插入及未知归属 fallback epoch；保留全局 retrieval_revision，纯权限 epoch 需另审计，不能直接重命名 |
| 6. progress / evidence / notes / event_query / sources / discover | 全部消费者支持 typed validity_mode 和相同依赖证明后才启 scoped；旧回执 global 模式分开保存。拟议 event-query v2 明确较细失效，不能把旧 v1 的全局校验悄悄绕过 |
| 7. main 当前请求投影与成对格式 | source-query v2/query-session v3 草案、可选 discover v1 与拟议 event v2 按本轮能力绑定；C2b 阶段未实现 range_batch 就不投影，scoped 不齐则保持 global；所有旧包原义和实际包数不变 |

`query_progress_revisions()` 当前只返回两个全局字符串，新依赖向量不能塞进同一 tuple 却让旧消费者当全局使用；需要明确的新内部验证器和旧入口兼容。`issued_sources` 当前按 source_ref 保存，分区/全局模式共存须按绑定和版本分型，避免一条新回执覆盖另一种模式。变更捕获和使用前核对均通过再启较细失效；批量、资源与复用可先在全局模式交付。

验收见[SQR-01--18](../../astrbot_plugin_private_companion/docs/MEMORY_COUNTEREXAMPLE_EVAL_V0.md#query-range-c3-evaluation)，全部 not_run。包括长消息半片、预算计量/并发、带新便笺的精确重试、空分区、外部写入口、旧/新回执和过期；同预算真实模型结果另记，不把较多返回消息直接等同于整周答案更准。

<a id="query-model-c4-adaptation"></a>

#### 4.2.5 C4 自主对照与真实计量的接点（D，2026-09-14）

主方案见[C4 设计](../../astrbot_plugin_private_companion/docs/MEMORY_QUERY_SESSION_DESIGN_V0.md#query-model-c4-design)，计量见[统一规范 §6.7](../../astrbot_plugin_private_companion/docs/PERFORMANCE_RELIABILITY_EFFECTIVENESS_EVAL_V0.md#memory-query-c4-measurement)。现有隔离脚本可以复用临时库、真实原生 handler/Schema 绑定和增量报告的实现，但不直接改个标题就当作新的完整验收器。

| 接点 | 已核对的限制 | C4 待实现 |
| --- | --- | --- |
| scripts/evaluate_recall_model.py | 使用基础检索、embedding 关闭，有限合成样例与简化角色；model_to_answer 从 inject_memories 之后开始，text_chat 非流式 | 冻结独立故事资产/真值隔离与版本 manifest，从初始注入前开始同预算计量；启用实际已交付路径及真实 embedding，旧历史报告不重算 |
| 实际工具/Prompt 绑定 | 旧脚本能记录实际提供的工具和调用；A/B/C2a 尚无可靠新宿主加载 | 每个变体记录实际 handler/Schema/提示摘要，候选只暴露已实现能力；主对照不给正确检索词、事件解释或便笺 |
| query_session / service / Provider 适配 | 现有默认步数不覆盖全部模型/token；C3 lease 和新 discovery 未交付 | 隔离外层 evaluation lease 先保证配对上限，后接实际 C3；真实重试/usage/未知费用/输出分别结算，外层能力不冒充宿主已接 |
| source_query / vector_search / 投影维护 | 脚本路线和 stub 向量仅有结构证据，冷建库及持续更新仍有成本 | 各变体使用独立资料副本/缓存和同一授权原始集合，记录索引完整度、冷暖/写入条件与所有建库成本；参考真值不从被测候选输出生成 |
| Host / Private / 平台 | reply_performance 只给部分阶段，Host 最终压缩上下文与平台可见首句未形成完整证据 | 用共同 trace 关联单调时钟 span 和实际传输回执，区分 Provider 片段、首字/首句/实质答案/完整终态；无观测字段保留 unknown |
| 评阅与报告 | 现有局部模型样本需要人工语义评阅，B 便笺自主收益未证 | 匿名全答案评阅、所有准入失败分母、按故事组配对统计，来源/取证/理解/传输缺口分列；辅助模型评阅在离线且费用单列 |

拟议评估 manifest/资产/报告先作为隔离评估文件，不新增面向 Bot 的工具或公共协议，不修改现有 9 个公共 review 包/4 个本地包。代码、环境和资产摘要包含未提交改动，不能只记录 commit 就宣称输入完全固定；报告不含 Provider 凭据。已有脚本的 resume 不自动满足 C4 冻结条件，新编排必须核对所有依赖与预算、保留真实 attempt，不能只按 case ID 跳过旧结果。

实施时先用固定 tape 验证真值隔离、计时起点、流式 usage 去重、预算/取消和报告断点，再用真实模型取数；tape 不计语义或用户等待收益。[SQA-01--20](../../astrbot_plugin_private_companion/docs/MEMORY_COUNTEREXAMPLE_EVAL_V0.md#query-model-c4-evaluation)全部 not_run。实际开发仍 C2b→C2c→C3→C4，可靠加载/平台投递观测独立验收；可信原文捕获与漏捕补偿由下方 [CAP 接点](#source-capture-adaptation)承接，不由评估器补写推测历史。

### 4.3 账本、事件与存储边界

设计阶段不迁移旧库、不批量改表，也不为新框架复制第二套权威记忆。先用隔离测试资产验证接口，再确定 owner 内部最小事务扩展。存储选型优先评估现有 ScopedStore 的 revision、去重和生命周期机制。

标准写入需要事实、ProposalReceipt 和 memory.changed outbox 在同一提交边界落地。若事实写在旧库、回执写在外部 sidecar，则不具备这一保证，不能宣称 succeeded 的可靠恢复语义。后续可以通过 owner 内部的增量事务能力实现，必须单独设计和验收；仅增加 facade 无法补齐。

新旧路径共享同一 owner 时统一经过同一个事务入口；在所有写入口完成授权和 revision 约束前，新 Writer 仅用于隔离验证。切换按稳定 owner 交接，旧命令/页面可以转接同一用例，避免无条件双写。旧格式不能无损回退时保留明确降级并对账，不拿旧快照覆盖新增事实。

<a id="source-capture-adaptation"></a>

#### 4.3.1 原文保存、补偿和可信恢复接点（更新 2026-09-16）

完整语义由[捕获专题](../../astrbot_plugin_private_companion/docs/MEMORY_SOURCE_CAPTURE_RECOVERY_V0.md)维护，公共版本边界见[接口](../../astrbot_plugin_private_companion/docs/MEMORY_PROPOSAL_QUERY_CONTRACT_V0.md#source-capture-interface)。本地 source_capture/capture_runtime 已实现完整脱敏正文、chunks、事务回执、lookup 与治理抑制，Private 已接入站/输出持久交接和本机撤回；证据见[09-16 报告](../../astrbot_plugin_private_companion/docs/evaluations/S4_LIFE_COMPLETE_20260916.md)。来源保存不复用 MemoryAtom proposal ID，也不开放给普通模型冒写原话。下表是完整适配要求，局部已实现与剩余范围以上述报告为界。

| 接点 | 完整适配要求 |
| --- | --- |
| Private final_response_persistence / 主动 bridge | 稳定 delivery/part 与原时间；每个 sink 独立持久状态，Memory 失败不被聚合 persisted/duplicate 短路，不重复已发消息 |
| main hook / service._capture_async | 最早可信入站边界形成持久原文任务；raw capture 脱离 classifier/重要性判断及注入之后的易失后台任务，生成结果与实发来源分型 |
| service.record_visible_turn / sanitizer | 保留旧 str 兼容入口，新绑定按实际正文组件处理；消除受信原文的多层静默截断/词面整条过滤，脱敏版本/实际缺口不丢 |
| store.add_timeline_event / schema 初始化 | 新完整来源/chunks/receipt/source-change/staging 与抑制记录；同 key payload 冲突、完整身份、事务 fence 与 lookup，不直接改旧 INSERT OR IGNORE 语义 |
| source_query / source_evidence / navigate / events / notes | 共用 canonical reader 的正文版本/坐标与保存完整度；新格式来源不被旧 v1 当截短全文，所有消费者及候选额度前的兼容行为需验证 |
| C2b/c/C3 维护与 summary | 完整正文候选/精确读取，尾部也可检索；source-change 驱动 dirty、分页/便笺失效与晚到反思补处理，不强制同步 embedding |
| dispatcher / close / aclose | 持久 next_attempt/lease/generation，有界恢复与退避；取消/关闭跟踪 SQL 完成，旧 worker 不回写，不每分钟扫全库 |
| chat_import / 历史 timeline 批次 | 可信 manifest/原 ID/时间/完整归属映射，逐条 capture 回执和 checkpoint，冲突/抑制检查；截图另存证据类型，不按同句补造原生 ID |
| Image / Together / 其它原生来源 | 分别适配实际 owner 回执与同一消息身份；保持房间保存开关，STT/播放/生成与实际文字消息区分，普通状态日志不是原话 |

本地采用完整 timeline 兼容投影，完整脱敏正文与规范 chunks/回执保持同一来源身份，旧查询沿授权读取；不截短冒充全文，也不宣称公共新版本已经发布。source/navigate/events 已有局部回归，全部索引、便笺、摘要、反思和保留消费者仍需整链验证。CAP-1/2 本地切片不关闭 CAP-3 库存与可信恢复、CAP-4 公共消费绑定；实际查询开发仍先 C2b。

[CAP-01--24](../../astrbot_plugin_private_companion/docs/MEMORY_COUNTEREXAMPLE_EVAL_V0.md#source-capture-evaluation)全部 not_run；当前 4 个本地包及 9 个公共 review 包不变。生产日期缺口、旧人格归属、公共协商、A/B/C2a 实际请求与生产效果及 S3 非空完整重启继续待验。

<a id="reflection-life-adaptation"></a>

#### 4.3.2 生活反思与长期认识的接点（D，2026-09-16）

公共语义以[反思批次与认识交接](../../astrbot_plugin_private_companion/docs/MEMORY_CONTRACT_V0.md#reflection-life-handoff)为准，S4-COORDINATION-D01 不新增另一套记忆写接口。当前 Private 工作反思归档是局部基础，以下完整适配仍待实现。

| 接点 | 适配责任 | 不能由局部成功推出 |
| --- | --- | --- |
| 输入与查询 | 接受受信 Actor/关系授权和实际 source/version/span；新执行轮重建 C3 子账，取得当前有效来源 | observed_hooks_only 等于全天完整，或旧轮次 lease 可跨日授权 |
| 分析结果 | 原作业持久保存 batch revision、输出 item 身份、处理声明和未覆盖范围，再调用现有 extract/proposal 职责 | 报告保存等于全部记忆、世界习惯和关系已修改 |
| Writer 与查账 | 每 item 的原逻辑键绑定 payload；沿原 proposal/operation 与 expected_revision 校验、提交、查询，成功项不重写 | 新 attempt 可绕过旧未知操作，或 Memory 可直接修改 World/Relationship |
| 事件与治理 | 原 Memory 事务保存变更/回执/outbox；纠正、删除和撤权使相关 batch/派生认识/索引失效并通知作业 owner | ACK 丢失需重跑模型，或未登记依赖便不受治理影响 |
| 后来采用 | 当前有权版本进入查询/连续性投影；分别取证可查询、实际输入、采用和效果 | 多次日记/转述是独立证据，或文本习惯可以越过 World 已接受行为版本 |

ReflectionBatch/Coverage 属原作业 owner，Memory 只持有本域提议结果及必要因果引用。跨 owner 部分成功保持各自状态，版本冲突留下重验任务；来源过期按治理结清排除，不伪称已分析。定向验收见[S4C-17--24](../../astrbot_plugin_private_companion/docs/PERFORMANCE_RELIABILITY_EFFECTIVENESS_EVAL_V0.md#s4-coordination-eval)，既有 DR/MRQ 与 CAP 状态保持。

### 4.4 公共身份到旧命名空间的映射决策

2026-09-07 核对核心 `identity_namespace.py` 与 Memory 的 [core/namespace.py](../core/namespace.py)：当前契约名为 chat.namespace_context.v1，指纹均为 `49398a609b60cadf`。新字段与可校验样例见[公共身份与记忆契约包](../../astrbot_plugin_private_companion/docs/contracts/v1/README.md)。以下确定映射条件，不宣称通用转换器已经实现。

三种身份分别解析：scope.user_id 是当前平台发言者映射，owner.subject_ref 是记忆空间归属主体，proposal.subject/query.subjects 是断言主体或过滤条件。群成员、第三方转述和代办调用中三者不能互相替代。

映射按以下顺序完成：

1. 从经过认证的能力句柄取得真实调用方、目标 provider/generation、有效 scope 与授权快照。请求中的 provider_id 是目标提供方，不能被解释为调用者身份。
2. 通过已登记的 installation lineage、IdentityBinding、ConversationBinding 和人格绑定，解析规范主体与会话；重验绑定 revision。没有映射时返回 scope_unresolved，不按相同数字 ID 或昵称合并。
3. owner 根据实际授权确定稳定元组与 visibility namespace，再检查 payload 的业务 namespace、visibility、purpose 和 subjects 是否在申请范围内。payload 不能直接选择 NamespaceContext.kind 或替换 owner。
4. 按明确的兼容策略取得 legacy identity/group/persona 映射、assurance、profile_status、policy_version 和 migration_epoch。分别保留 persona binding revision、授权 revision、provider generation、迁移 epoch 和事实 revision。
5. 证明旧存储分区与该逻辑归属匹配后，建立原契约 NamespaceContext，经过 validate_namespace_context、AssurancePolicy 及原读取入口需要的来源证明；返回前重新验证授权和 revision。

| 新字段或上下文 | 旧契约落点 | 约束 |
| --- | --- | --- |
| ecosystem_id / installation_id / bot_id | 旧 NamespaceContext 没有对应字段 | 由可信 StoreBinding 绑定已隔离存储/投影；不能丢弃后访问共享分区 |
| persona_id | namespace.persona_id | 已登记的逻辑人格映射；不能为隔离临时拼造新人格 ID |
| owner.subject_ref | 私有/成员命名空间的 identity_id，或群/人格主体的专门映射 | 身份映射由可信来源提供；不能直接复制 scope.user_id |
| conversation_ref / platform group mapping | group_id 或会话上下文 | 使用登记的群绑定；不把私聊 ID 填入 group_id |
| 调用用途 | query 对应 memory_read，事实写入对应 memory_write | 先校验新用途授权，再按具名策略映射旧操作用途；不能只改成 memory_read 就跳过用途限制 |
| assurance / profile_status / policy_version | 同名字段 | 来自当前可信身份/授权服务，不从外部 JSON 或模型理由补值 |
| migration_epoch | 同名字段与存储激活 epoch | 由存储迁移状态确定，不能使用 runtime generation 替代 |
| runtime_instance_id / provider_generation / session_id | 运行时准入、任务及临时可见性 | 不进入稳定 owner；SessionContext 也不能替代授权凭据 |

按 kind 的映射分支：

| 获授权空间 | 旧 kind / 主体字段 | 当前兼容结论 |
| --- | --- | --- |
| 用户私有记忆 | private；identity_id 有值，group_id 为空 | 身份、人格、用途及存储分区均获证明后可进入旧 memory_read/write |
| 群内某成员的记忆 | group_member；identity_id 与 group_id 均有值 | 群内范围不升级为该用户私聊范围 |
| 群共同空间 | group_shared；identity_id 为空，group_id 有值 | group_shared 的事实 owner 是群空间，不能冒充某位发言人的个人档案 |
| 人格公共记忆 | persona_global；identity_id/group_id 均为空 | 旧 AssurancePolicy 只允许 rule_read/write；不能强行映射成 private 来读取记忆 |
| 未确认身份空间 | pending | 旧正式记忆访问拒绝；它与 MemoryProposal.pending 完全不同 |

旧上下文的 cache_scope 只包含 kind、persona/identity/group 哈希、policy_version 和 migration_epoch。改变 ecosystem、installation 或 bot 时，旧缓存键可能完全不变；因此该键不是新 owner 的完整标识。只读适配需要独立的可信存储分区或已证明隔离的投影，跨 owner 缓存还必须包含新逻辑边界和当前授权版本。

首个隔离参考适配器可绑定一个明确的 owner 分区进行验证；当两个逻辑 Bot 共享旧文件且没有隔离证明时，对应能力保持 unavailable/scope_mapping_unavailable。不能靠添加一个未执行过滤的新字段、复用裸 SessionContext、设置 admin_read_all 或构造假的 event 获得授权。

兼容拒绝与运行错误分别表达：缺必填 scope 为 rejected/scope_required；身份或 lineage 未解析为 rejected/scope_unresolved；已确认的权限不足为 permission_denied/forbidden；旧存储无等价映射为 unavailable/scope_mapping_unavailable。不可见目标和不存在目标继续采用同一 target_unavailable 行为，避免探测隐私。

契约包中的 11 个兼容案例验证两份旧纯模块的形状、策略和遗漏逻辑边界的事实。真实 binding 服务、P5 证明、存储分区和授权撤销仍需只读参考验证；不将这些静态案例记为迁移通过。

## 5. 注册、启动和停止的映射

1. manifest() 返回稳定插件身份、实际可提供能力及其 schema；MemoryExtensionDescriptor 关联已验证的 features、limits 和 type_schemas。当前 metadata 插件版本不直接当作能力版本。
2. setup(ctx) 挂接 handler、证据解析和任务句柄，只准备适配器自有资源。probe 返回真实就绪与契约覆盖，不执行测试写入或模型调用。
3. start() 复用插件 initialize 已拥有的维护任务；已有任务可托管给 Supervisor，但不能再次创建同样的 dispatcher、嵌入循环或摘要 worker。
4. release/stop(adapter) 只关闭该适配器的准入、订阅和请求任务。核心重载时 Memory 仍可能服务于旧工具和页面，不能整体 aclose。
5. AstrBot terminate(whole plugin) 先注销准入/fence 旧代，再等待任务与提交收束，最后复用 bridge.deactivate/service.aclose 的资源关闭。残留线程未隔离时不允许新代 Writer 接管同一 owner。

现有 aclose 能取消并等待多类任务，是需保留的基础；新设计额外要求有限 shutdown budget、可证明的提交状态和残留资源诊断。不能由“cancel 已发送”推断 sqlite 线程写入已经停止。

## 6. CapabilityCoverage 初稿

| capability_id / owner | 用户能力与旧入口 | state | 新契约/权限 | 失败恢复与验证 |
| --- | --- | --- | --- | --- |
| memory.proposal.submit / Memory | 留住、纠正、撤回事实；tool_remember、scoped mutation | redesigned | proposal.v1；propose/correct/retract 分开授权 | 冲突拒绝，提交未知查账；EXT-08/09/12/14、LC-05 |
| memory.query / Memory | 按用途回忆与解释；tool_recall、search_context_slots | redesigned | query.v1；read + namespace/purpose | 过滤不丢失，局部检索失败可降级；EXT-01/02/03/10/11/13 |
| memory.operation.get / Memory | 查看写入结果与恢复依据；旧 memory_id/工具回执待重建 | redesigned | operation-query.v1；调用方/管理者授权 | 无账本不猜执行结果；EXT-08/12、LC-08 |
| memory.changed / Memory | 纠正、撤回后下游及时失效；现有缓存/存储 revision | redesigned | changed.v1；独立 subscribe | outbox、去重、游标过期重同步；EXT-10/12、LC-07 |
| 物理擦除、批量治理、全量导入导出 / Memory | 原页面/命令保留 | deferred | 公共功能对等清单，专属治理协议待补 | 不用 retract 伪装擦除，不提前停旧入口 |

这里的 redesigned 表示设计决策，ready/通过状态另外记录，目前均待新契约验证。功能对等范围遵守[公共清单](../../astrbot_plugin_private_companion/docs/FUNCTIONAL_COVERAGE_AND_PARITY.md)，未列出的旧能力不能据此认定被删除。

## 7. 验收与实施前决策

2026-09-14 的[S3 联合验收设计](../../astrbot_plugin_private_companion/docs/S3_INTEGRATED_ACCEPTANCE_V0.md)补充当前执行顺序：只读收集真实 owner/实例/版本及非空基线，隔离验证真实事务/进程故障，再采集生产纠正、活动/反思和 Desktop 完整重启。实际修订、Bot Personal、CAP 来源、World/Calendar 与 Delivery 分开查原操作；跨轮 run_id 只关联真实 trace，不替代幂等键或生成新公共封套。现有 Bot Personal outbox 和尽力失效通知不能充作标准订阅证明。SAC-01--20 全部 not_run；独立结构、完整写入口/订阅/消费绑定与可靠宿主恢复仍待实现/验收。2026-10-08 本地已完成 C2b context、C2c 维护/候选检索/工具绑定和 C3 范围批读基础；SQB/性能、真实 embedding 和完整 C3 资源/回放验收仍待推进。

共同使用[第三方一致性验收规范](../../astrbot_plugin_private_companion/docs/MEMORY_COUNTEREXAMPLE_EVAL_V0.md)的 EXT-01 至 EXT-14 和 LC-01 至 LC-08。第一轮可用隔离目录、受控时钟、录制语义结果与测试替身；报告标出真实 handler、存储或网络实际覆盖到哪一层。

实施前的三项决策进度：RuntimeScope 到 NamespaceContext 的映射条件已在 4.4 明确，实际绑定和分区证明待验证；现有 ScopedStore 的事务基础可以评估复用，但事实/回执/outbox 同提交及旧代隔离尚未实现验收；所有写入口统一经过 owner 的改造仍待可靠记忆切片。未解决的条件不通过新增 facade 自动成立。

首版[公共机器契约与兼容夹具](../../astrbot_plugin_private_companion/docs/contracts/v1/README.md)已经形成，成熟度仍为 `review`；本仓库另有 source-query v1/v2、event-query v1、query-session v1/v2/v3 六个局部包。它们证明的格式、隔离行为和生产状态必须分开记录。

当前实施顺序以路线看板为准：C2b 时间/短词 FTS5 和写入维护边界审查冻结后先做 C2c-1 片段依赖及独立 semantic dirty，再完成 C2c 实际检索、C3 范围/共同资源/复用和 C4 同预算模型验收；CAP-1--4 独立落地，但必须与完整 reader 和消费侧一起启用。随后按 S3 联合验收取得真实非空起点、生产纠正、活动/反思、回执查账和受控完整重启证据。只有公共能力协商、标准订阅、独立结构、可靠恢复和阶段退出条件都满足后，才定型 SDK 或切换生产作用域。
