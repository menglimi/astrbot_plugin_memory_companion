# 记忆参考适配器设计 v0

> 导航：[设计总纲](../../astrbot_plugin_private_companion/docs/FRAMEWORK_DESIGN.md) / [主题目录](../../astrbot_plugin_private_companion/docs/FRAMEWORK_DESIGN_INDEX.md)。定位：领域接入设计草案；依赖公共生命周期和记忆接口，验证旧入口、事务与隔离。

> 状态：2026-09-07 设计草案与代码映射。尚未新增运行时适配器、迁移数据库或发布 memory.api；旧插件继续按原接口理解。

本稿说明 `remember_you` 如何成为新框架首个 Memory Service 参考提供方。公共字段见[记忆外部接口](../../astrbot_plugin_private_companion/docs/MEMORY_PROPOSAL_QUERY_CONTRACT_V0.md)，注册、绑定、调用与卸载见[外部插件生命周期](../../astrbot_plugin_private_companion/docs/COMPANION_EXTENSION_LIFECYCLE_V0.md)。领域适配不复制公共协议。

## 1. 身份与适配边界

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

### 4.3 账本、事件与存储边界

设计阶段不迁移旧库、不批量改表，也不为新框架复制第二套权威记忆。先用隔离测试资产验证接口，再确定 owner 内部最小事务扩展。存储选型优先评估现有 ScopedStore 的 revision、去重和生命周期机制。

标准写入需要事实、ProposalReceipt 和 memory.changed outbox 在同一提交边界落地。若事实写在旧库、回执写在外部 sidecar，则不具备这一保证，不能宣称 succeeded 的可靠恢复语义。后续可以通过 owner 内部的增量事务能力实现，必须单独设计和验收；仅增加 facade 无法补齐。

新旧路径共享同一 owner 时统一经过同一个事务入口；在所有写入口完成授权和 revision 约束前，新 Writer 仅用于隔离验证。切换按稳定 owner 交接，旧命令/页面可以转接同一用例，避免无条件双写。旧格式不能无损回退时保留明确降级并对账，不拿旧快照覆盖新增事实。

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

共同使用[第三方一致性验收规范](../../astrbot_plugin_private_companion/docs/MEMORY_COUNTEREXAMPLE_EVAL_V0.md)的 EXT-01 至 EXT-14 和 LC-01 至 LC-08。第一轮可用隔离目录、受控时钟、录制语义结果与测试替身；报告标出真实 handler、存储或网络实际覆盖到哪一层。

实施前的三项决策进度：RuntimeScope 到 NamespaceContext 的映射条件已在 4.4 明确，实际绑定和分区证明待验证；现有 ScopedStore 的事务基础可以评估复用，但事实/回执/outbox 同提交及旧代隔离尚未实现验收；所有写入口统一经过 owner 的改造仍待可靠记忆切片。未解决的条件不通过新增 facade 自动成立。

首版[机器契约与兼容夹具](../../astrbot_plugin_private_companion/docs/contracts/v1/README.md)已经形成，成熟度仍为 review。下一步通过最小 facade/隔离查询验证上述映射、证据和返回边界，再按验证结果定型 SDK；之后才接入可靠写入/回执/事件。完整记忆闭环及故障验收通过后，才讨论生产作用域切换。
