# 我会牢牢记住你

`astrbot_plugin_memory_companion` 是面向 AstrBot 陪伴体系的记忆陪伴中枢。它不把聊天记录粗暴塞回模型，而是把当前消息、连续对话、长期记忆、Bot 自我时间线、群聊/私聊权限和外部陪伴插件线索分层整理，再在每轮 LLM 请求前生成一份临时、可解释、可排查的记忆包。

MemoryCompanion 是可独立安装和运行的记忆核心，不以 PrivateCompanion 或任何内容、图片、ComfyUI 扩展为启动依赖。只安装 Memory 时，采集、召回、权限、迁移、维护、命令和管理页照常工作；缺少 Companion 只会关闭陪伴状态投影与跨插件记忆协同。

- 插件名：`astrbot_plugin_memory_companion`
- 中文名：`我会牢牢记住你`
- 版本：`1.10.5`
- 适配平台：`aiocqhttp`
- AstrBot 版本：`>=4.22.0`
- 编码要求：UTF-8

## 支持开发者（自愿捐款）

**重要声明：**

- **捐款完全自愿** —— 捐不捐功能完全一样，不会有任何功能差异或特殊对待，纯粹是对作者的支持和认可
- **官方唯一捐款渠道：** [爱发电（Afdian）](https://ifdian.net/a/xuhaun) —— ifdian.net/a/xuhaun
- **内部交流群：** QQ 群 `1097283005`（可在群内拷打作者本人）
- **防骗警告：** 除上述爱发电链接和 QQ 群内与作者本人直接联系外，**任何其他渠道声称代表本插件接受捐款的皆为骗子**，请务必提高警惕，谨防上当受骗

## 设计目标

这个插件解决的是“Bot 如何自然地记住、想起、忘记和区分边界”。

它不会把对话记录等同于记忆。对话记录会先进入时间线，阶段性总结会把值得保留的内容沉淀为长期记忆；检索时再按当前用户消息、时间窗口、权限、召回模式和表达策略组织注入。记忆永远是当前回复的辅助资料，当前用户消息才是主任务。

与 `astrbot_plugin_private_companion` 一起使用时，推荐分工如下：

- PrivateCompanion：人格状态、日程表现、主动陪伴、环境感知、语气和生活化表达。
- MemoryCompanion：长期记忆、连续对话记忆、检索注入、权限边界、自然衰减、旧库迁移和调试日志。

## 独立运行、协同与信任边界

- Memory 主库就绪后即可运行核心链；可选 scoped namespace 故障只报告 degraded，不会拖垮普通记忆采集和召回。
- Companion 协同只通过 AstrBot 当前 active registry 与公开 bridge 协商。registry 明确不存在、实例未激活、generation 已替换或契约不完整时，协同能力关闭，不从残留模块恢复旧实例。
- 外部插件写入必须先用精确注册身份换取进程内、不可序列化的 producer capability，再由 Memory 服务端钳制用户、会话、scope 和可见性；调用方自报的 `source_plugin` 或 scope 不构成授权。
- 当前 N/N 契约是推荐组合；N/N-1 只保留已知公共字段的一个发布周期兼容。未知高版本、缺失方法和歧义实例 fail-closed。兼容入口至少经过一个发布周期并确认无使用后才会删除。
- Memory 不安装 Content、Image 或 ComfyUI 时不会启用任何对应功能，也不会扫描、调用或写入这些扩展的数据。

## 核心能力

- Token 可观测：独立记录阶段总结、重排、向量和维护整理的模型消耗；区分 Provider 已确认 Token、插件估算 Token 与失败调用，并可供陪伴插件 Token 页只读展示。
- 运行预设：提供轻量、标准、陪伴三种一键配置，保留已有 Provider 选择。
- 运维诊断：统一展示检索路径、缓存命中率、模型 Token、平均耗时和已知记忆插件共存风险。
- 可移植数据：UTF-8 JSONL 导出和恢复记忆、身份、关系、时间线与 ACL，导入前自动备份。
- 历史聊天导入：可通过 NapCat/aiocqhttp 直接读取指定 QQ 与时段，也可上传 TXT/LOG/Markdown 或 QQChatExporter JSON；人工确认用户与 Bot 后，按绝对时间分段提炼长期记忆、重要事件、日摘要、稳定事实和关系候选。

- 主链记忆注入：在 LLM 请求前临时注入结构化记忆包。
- 核心记忆：少量规则、边界、偏好和稳定事实按 Label 管理，在对应 Bot、人格和会话作用域内每轮常驻，不依赖 RAG 命中。
- 结构化记忆原子：统一保存所有者、人格、敏感级别、耐久度、有效期、证据、强化分和实际注入统计，旧数据在读取时兼容迁移。
- 分层检索路由：低信息、纠错、当前状态、时间窗口、最近上下文和长期记忆走不同策略。
- 多路融合召回：不同检索路线使用 RRF 融合，并用 MMR 抑制近重复候选；排序同时考虑相关性、时间有效性、显著度、自然衰减和真实注入强化。
- 连续对话记忆：群聊普通发言进入时间线，通过阶段性总结沉淀为长期记忆。
- 分槽编排：自我时间线、用户画像、当前窗口、阶段总结、稳定记忆分开召回。
- 当前状态保护：例如“吃晚饭了吗”“在干嘛”只允许近期且直接相关的状态记忆进入。
- 权限隔离：私聊、群聊、自我时间线、共享记忆和内部记忆分边界管理。
- 权限拓扑：用可视化连线管理窗口间读取方向，统一处理对象级权限配置。
- 语义检索增强：支持本地检索、Embedding 候选召回和 Rerank 二阶段排序。
- 短 TTL 检索缓存：同一会话、权限、query、检索配置和记忆库 revision 下，短时间重复召回会复用结果，减少重复 Embedding query / Rerank 调用。
- 注入可观测：测试版可把检索路径、选中记忆、过滤原因和最终注入包打到日志。
- 陪伴插件桥接：可接收外部事件、去重陪伴插件上下文，避免重复注入。
- LivingMemory 迁移：预览、导入、修复旧库内容，并自动区分完整摘要和碎片。
- 自然衰减：低价值、长期未访问的记忆可在睡眠维护中压缩或归档。
- 证据门控：阶段摘要的事实和关联必须指向可验证的时间线事件；证据不足时保留原始时间线并进入待审核隔离区。
- 全链路脱敏：凭据、令牌、私钥和敏感 URL 参数在持久化、向量化、导出和注入前统一清洗，启动维护会修复旧记录。
- 双界面管理：简洁管理与放映馆界面共用同一套后端能力，可在总览、工作区和详情中随时切换；覆盖私聊、群聊、个人记忆、用户画像、知识图谱、召回检查、维护迁移和配置。
- 页面能力契约：前端启动时核对后端契约版本、工作区和动态端点，版本不一致会明确提示，不会静默展示失效按钮。
- 原子级治理：详情页可查看 Bot/人格归属、实际注入与强化反馈，并安全调整有效状态、有效期、显著性、耐久度和敏感级别。

## 工作流程

每轮主链请求大致经过这些步骤：

1. 解析当前会话身份、范围、群号/用户号和真实用户消息。
2. 清理上一轮临时注入片段，避免历史 prompt 残留。
3. 判断本轮消息类型：时间窗口、最近上下文、纠错、当前状态、低信息、新话题或长期记忆检索。
4. 读取当前 Bot、人格和窗口可见的核心记忆静态槽，不进行相似度打分。
5. 构造检索 query，默认只使用当前用户消息；核心块不会再次进入动态候选。
6. 按可见性、ACL、窗口边界和生命周期筛选动态候选。
7. 使用本地评分、可选 Embedding 和可选 Rerank 排序。
8. 若短 TTL 检索缓存命中，会直接复用同一权限与同一记忆库 revision 下的结果；只有最后真正进入提示词的记录才更新注入统计与强化分。
9. 将结果分配到自我时间线、用户画像、当前窗口、阶段总结和稳定记忆槽。
10. 按表达策略分成 `mention_memory`、`tone_memory`、`uncertain_memory`。
11. 在统一字数预算内先组织核心记忆，再组织动态长期记忆并注入本轮请求。
12. 明确回忆、时间、个性化或多跳问题若仍缺证据，模型可基于已找到的线索逐步导航；普通聊天不启动这条路径。
13. 记录用户消息、Bot 回复和群聊普通发言到时间线，等待总结与维护。

## 检索架构模式

插件有两层检索配置，不要混在一起理解。

### 查询构造：`context_orchestration.query_mode`

- `current_message`：默认推荐。只用当前用户消息检索，最稳，不容易被旧上下文带偏。
- `guarded_companion`：只有陪伴插件线索和当前消息有主题重叠时，才扩展检索 query。
- `companion_augmented`：旧式增强，会直接拼接陪伴线索。召回更强，但更容易答非所问，建议只在排障或特殊场景使用。

### 检索执行：`retrieval.mode`

- `basic`：只使用本地候选、关键词、图谱扩展、时间窗口和本地评分。
- `auto`：推荐。检测到可用 Rerank Provider 时使用重排，否则回退 basic。
- `rerank`：强制尝试重排，失败仍回退 basic。

Embedding 是额外开关：开启后会为记忆建立向量索引，用语义相似度补充候选；Rerank 则负责在候选池上做二阶段排序。日志中的 `retrieval_path` 会显示实际走的是 `basic`、`rerank` 还是 `fallback_basic`。

短 TTL 检索缓存只缓存最终检索结果，不缓存或放宽权限判断。缓存 key 会包含当前会话、群/用户、管理员读取权限、`top_k`、时间窗口意图、分槽上限、检索模式、Embedding/Rerank、可见性配置和单调递增的数据库 revision；记忆、ACL、向量或知识图谱变化后，revision 会立即改变。即使命中缓存，插件仍会重新读取当前记录并执行可见性与 ACL 判定。日志中的检索路径会显示 `cache=hit` 或 `cache=miss`。

## 主动记忆重建

普通聊天继续使用原有一次检索与分槽注入，不增加 Agent 循环。只有明确回忆、时间、个性化或复杂记忆问题会收到重建提示：模型先使用本轮已经注入的证据，仍不足时才调用 `memory_companion_navigate`，从首轮证据提炼下一条人物、主题、时间、关联维度或记忆 ID。默认最多 3 步、每步 6 条候选；这是资源上限，不要求用满。

新生成的阶段总结可附带 `Cue -> Tag -> Content` 关联提示。Cue 可以是人物、地点、对象、事件或时间线索，Tag 描述关联维度，Content 必须仍由原始总结窗口支持。关联只负责路由，最终回答证据始终来自实际记忆记录。升级前已有记忆仍可通过原有人物、主题、事实图和普通检索参与导航；不会为了补齐关联而凭空改写旧记忆。

每一步都会重新读取来源记忆，并重新检查平台、Bot 所有权、窗口可见性、ACL 和当前群发言者。撤权会在下一步立即生效；不可见图节点、边、记忆 ID、数量和内容不会作为工具结果返回。相关资源上限位于 `memory_reconstruction`，工具总开关位于 `memory_tools.enable_reconstruction_tool`。

## 注入包形式

注入包会明确告诉模型：

- 这是临时记忆资料，不是新的用户消息。
- 先回答 `current_user_message`。
- 记忆只在直接相关时补充。
- 与当前消息冲突时，以当前消息和用户纠正为准。
- 不要泄露其它窗口的私密内容。
- 未来安排、身份和共同经历会区分明确记录、稳定习惯与合理推测；没有直接证据时保留不确定感，不把推测包装成“你又忘了”。
- 群聊阶段总结属于多人背景，其中的计划和经历只归属明确点名的成员，不会被当作 Bot 或当前用户的自我事实。
- 群聊中 Bot 明确说出的日程、承诺或行动会带原始 Bot 回复证据单独沉淀为自我时间线；摘要本身不会因一个标记而升级为 Bot 事实。
- 注入包会在预算内按完整记忆条目生成并保留结构闭合；聊天历史、记忆正文和协同线索均作为不可执行资料处理。
- 深夜“在不在/睡了吗”和查岗类状态确认只会带入轻量熟悉感，不展开旧记录中的私密细节；“例行检查/晚间检查”等可能属于双方约定简称的表达，会综合当前上下文与重复记忆判断，证据不足时自然确认；密码、口令、验证码和令牌值不会进入主链注入或调试日志。

记忆会按表达用途分组：

- `mention_memory`：可以自然提及。
- `tone_memory`：只影响语气和关系感，不复述具体内容。
- `uncertain_memory`：低置信或旧记忆，只能带不确定感。

## 快速开始

### 安装

将插件目录放入 AstrBot 插件目录，建议目录名保持为：

```text
astrbot_plugin_memory_companion
```

常见路径：

```text
C:\Users\你的用户名\.astrbot\data\plugins\astrbot_plugin_memory_companion
```

运行数据默认在 AstrBot 插件数据目录下的：

```text
astrbot_plugin_memory_companion
```

### 推荐初始配置

1. 保持 `memory_capture.enabled=true`。
2. 保持 `memory_summary.enabled=true`，按需配置 `memory_summary.private_provider_id` / `memory_summary.group_provider_id`；不区分会话时仍可只配置兼容字段 `memory_summary.provider_id`。
3. 保持 `memory_injection.enabled=true`。
4. 检索模式使用 `retrieval.mode=auto`。
5. 初期不急着启用 Embedding；记忆变多后再配置 Embedding Provider。
6. 有 Rerank Provider 时选择对应 Provider ID，例如硅基流动的 bge reranker。
7. `context_orchestration.query_mode` 保持 `current_message`。
8. `memory_injection.debug_log_injection_enabled` 默认关闭；仅在排障时临时开启，完成后立即关闭。

## 配置重点

### 记忆捕获

`memory_capture` 控制用户消息、Bot 回复、稳定事实和关系边的记录。当前版本不会把原话直接写成长期记忆；原始消息主要进入时间线，长期记忆由总结和明确工具写入产生。

### 阶段性总结

`memory_summary` 控制时间线压缩为长期记忆的节奏。总结输入会作为不可信消息处理，提示词注入、角色覆盖和系统指令伪装会被标记与清洗，降低总结被带偏的概率。

私聊和群聊可以分别选择总结模型：`memory_summary.private_provider_id` 只处理私聊时间线，`memory_summary.group_provider_id` 只处理群聊时间线。对应的 `private_fallback_provider_id` / `group_fallback_provider_id` 用于主模型失败时的备用尝试；未填写专用字段，或专用模型调用失败时，会兼容使用 `provider_id` / `fallback_provider_id`，再回退到当前会话模型。这样可以为群聊选择更轻量或更擅长多人对话的模型，同时不影响已有配置。

如果日志显示请求 `127.0.0.1:11434` 超时，含义是本机 Ollama 没有在期限内生成总结，不是记忆数据库损坏。当前版本默认最多等待 180 秒、单个 Provider 只请求一次；失败后会尝试不同的备用 Provider，并完整保留尚未总结的时间线。可在这里换用更轻的本地模型或独立总结 Provider，并按机器性能调整“总结模型超时秒数”。

### 重要性评估

新记忆写入时会经过统一的重要性校准。插件会保留来源给出的基础分，再结合长期陪伴价值微调：明确要求记住、用户偏好/画像、关系变化、约定、日程、创作内容、情绪转折、阶段总结的关键事实数量和置信度都会提高分数；普通短句、寒暄、低信息原始事件会被压低。

校准结果写回 `importance`，并在 metadata 中记录 `base_importance`、`importance_evaluator` 和 `importance_source`。同时会记录拟人化维度：`persona_importance`、`relationship_weight`、`emotional_weight`、`promise_weight`、`open_loop_weight`、`emotional_debt_weight`、`creative_weight`、`preference_weight`、`self_continuity_weight`、`freshness_weight`、`scar_weight`、`last_emotional_touch_at`、`relationship_phase`、`decay_mode`、`mention_policy`、`mentionability_score` 和 `memory_reason`。

召回会轻微优先这些关系、承诺、未完成、情感债务、情绪伤痕和创作节点，但不会让硬规则压过语义相关性。“继续”“还有呢”“后来呢”这类低语义追问会优先查看 `open_loop` 槽，再走普通语义召回。普通事实会随时间逐渐降权；承诺、冲突/修复/安慰、重要创作节点会进入 `no_decay`、`scar_slow_decay` 或 `creative_milestone` 等慢衰减策略。

注入结构会按拟人化用途分区：`open_loops` 放未完成事项和承诺，`relationship_memory` 放关系线索，`emotional_context` 放情绪脉络，`creative_threads` 放创作连续性，`self_continuity` 放 Bot 自我日程与主动行为，`stable_facts` 放偏好、画像和稳定事实。每条记忆仍保留“可明说/只调语气/不确定”的用法标记。

与主动陪伴插件配合时，陪伴插件负责当前状态、即时日程、情绪底色和主动行为提示；MemoryCompanion 只补充长期解释层：为什么这个状态重要、它和用户有什么关系、过去是否有类似情境、还有什么未完成话题可以自然接上。检测到陪伴插件已注入当前状态后，MemoryCompanion 会过滤近期“当前状态复读”型记忆，只保留有关系、承诺、创作或伤痕意义的长期线索。

### 外部插件长期记忆接入口

其他 AstrBot 插件可以通过记忆插件公开的 `get_memory_companion_bridge()` 获取桥接对象。管理员需先把该插件的 `root_dir_name` 加入 `private_companion_bridge.external_memory_producer_allowlist`（默认为空）；PrivateCompanion 仍由内置严格身份规则识别。插件必须用当前活跃实例换取不可序列化的能力，再绑定精确用户：

```python
bridge = memory_plugin.get_memory_companion_bridge()
capability = bridge.register_external_memory_producer(self)
producer_context = bridge.create_external_memory_context(
    capability,
    user_id="用户平台 ID",
)
result = await bridge.record_external_memory(
    producer_context=producer_context,
    content="用户最近开始每周慢跑三次，通常在晚饭后进行。",
    idempotency_key="weekly-summary:2026-08-25",
    payload={"activity": "running", "frequency_per_week": 3},
)
```

该入口的来源 ID、用户所有权、会话命名空间和 `private_pair` 可见性全部由 MemoryCompanion 根据注册元数据生成；调用方传入的 `source_plugin`、scope、session 或 server 字段不具有授权效力。无有效能力/上下文的旧调用会返回 `producer_capability_required`。重复上传同一 `idempotency_key` 会更新同一条记录；若只想暂存候选，可传 `long_term=False`。

PrivateCompanion 读取日程连续性或每日穿搭时会协商使用 `schedule_fast` / `outfit_fast`：通过短生命周期只读连接，按 Bot 所有者和当前私聊对象隔离后均衡读取相关日程、行动、边界、历史穿搭与自拍，不调用 Embedding、Rerank 或全库候选。两个快速路径可在“陪伴插件协同”中分别关闭并回退完整检索；普通聊天召回始终使用完整检索链。

`private_companion_bridge.cross_window_emotional_continuity_enabled` 默认关闭。只有明确开启并由新版陪伴插件提交精确用户能力上下文后，其他会话的近期情绪余波才会进入当前窗口；不会提供无身份的全局读取。

旧版陪伴插件可在过渡期通过 `private_companion_bridge.legacy_emotion_compatibility_enabled` 读取当前精确私聊窗口的脱敏情绪事件，默认开启；该路径不允许跨窗口聚合。陪伴插件升级到能力上下文接口后可关闭此项。

本版本的 Bot Personal 档案、用户记忆摘要、关系投影和表达决策接口需要新版陪伴插件传入由 Memory 签发的能力/上下文；旧版调用会明确返回降级或禁止状态，不会静默写入或读取其它用户、窗口的数据。升级两侧后再启用对应功能即可。

记忆被自然提及后，下一条用户回复会作为轻量反馈写回对应记忆：接受会提高 `mentionability_score` 和置信度；被安慰到会提高情绪权重；尴尬、否认或纠正会降低可提及性，并设置 `mention_policy=avoid_unless_asked` 或记录 `user_correction`。这样 Bot 会逐渐学习哪些旧事可以轻轻提，哪些只能当语气底色。

`mention_policy` 分为四档：

- `direct`：稳定事实或用户明确要求记住的内容，可在需要时自然明说。
- `soft_echo`：关系、承诺、创作和未完成事项，适合轻轻呼应，不要像查档案一样复述。
- `tone_only`：情绪脉络、Bot 自我状态和敏感背景，只影响语气与分寸。
- `avoid_unless_asked`：冲突伤痕、用户尴尬/否认/纠正过的内容，除非用户明确问起，否则不主动提。

### 连续对话

`conversation_memory` 记录群聊普通发言与短期上下文。它不会直接把原始窗口整段塞给主链，而是用于补全追问、判断话题变化，并在达到阈值后总结为阶段性记忆。

私聊还会从同一会话近期时间线提取少量即时事实锚点，默认只看近 3 小时、最多 4 条，覆盖吃饭、洗澡、上下班、所在位置和休息等容易被后续闲聊遗漏的状态。它不会回灌整段聊天，也不会把这些临时状态写成长期记忆；如果 Bot 已经围绕某条状态回应过，提示只会轻量提醒模型别重复询问，并在没接上时自然承认，而不是编造“刚才没看到”。

私聊与群聊切换时，插件默认还会生成一个近 30 分钟、最多 6 条的短时跨窗口上下文。它同时校验平台、Bot 和当前用户，只保留该用户与同一 Bot 的必要往返，并交给模型判断当前消息是否在语义上继续刚才的话题；换题时应直接忽略。群聊流向同一用户私聊可自动衔接，私聊流向群聊仍要求当前用户在群里本轮明确授权，不会因普通提问自动公开私聊内容。相关时效、条数和方向策略位于 `conversation_memory_advanced`。

上面这条“本轮明确授权”只约束近端原始聊天片段。已经整理成长期记忆的内容使用权限拓扑：为“私聊用户 -> 群聊”建立手动允许后，同一用户在该群自然询问“我中午吃了什么”“说说我喜欢的店”时，直接相关的候选可以参与回答，不必每次补一句“你还记得吗”，也不依赖固定疑问词。代码仍严格校验同一平台、同一 Bot、当前发言者本人、精确 ACL 和实际检索相关性；通过后由提示词判断当前核心意图是否需要该候选。权限不会把整段私聊搬进群聊，普通陈述、无关话题、未授权群、撤销后的规则和其他成员的自然提问都不会被要求主动展开私聊记忆。

低信息输入和自拍、图片、查询等新话题仍会抑制无关长期记忆，但不再原地裁剪 AstrBot 的原始会话历史，避免一次新请求把前面已经确认过的即时事实从后续会话中永久挤掉。

### 当前状态问题

“吃晚饭了吗”“在干嘛”“累不累”“今天穿什么”这类问题不会直接拉很久以前的长期记忆。插件只允许近期、直接命中当前状态锚点的记忆进入，否则会提示主链不要用旧记忆回答当前状态。

### 权限与隐私

默认边界：

- 私聊记忆默认不开放给其它窗口，需要在权限拓扑里显式连线允许。
- 群聊窗口之间按默认策略读取，具体窗口间的放行/阻止统一在权限拓扑里切换。
- 多 Bot 共用同一群聊记忆库时，Bot 第一人称阶段总结会绑定当前 Bot；其它 Bot 不会读取这类 Bot 视角记忆。
- 私聊流向群聊需要显式允许。
- 权限拓扑的箭头方向是“记忆来源 -> 可读取窗口”；需要让私聊记忆进入某个群时，应允许“该私聊用户 -> 目标群聊”。
- 内部记忆不参与普通注入。
- 归档记忆不参与普通检索。

可见性类型：

```text
private_pair   当前私聊可见
group_public   群聊公共记忆
bot_self       Bot 自我时间线
shareable      可共享记忆
internal       内部记录
```

## 命令

主入口是 `/mcomp`。

| 命令 | 说明 |
| :--- | :--- |
| `/mcomp status` | 查看插件状态、记忆数量、时间线、关系边和数据库路径 |
| `/mcomp search <关键词> [k]` | 按当前会话可见性检索记忆 |
| `/mcomp explain <关键词> [k]` | 查看召回、分槽和过滤原因 |
| `/mcomp recent [数量]` | 查看最近可见记忆 |
| `/mcomp add <内容>` | 手动添加当前会话记忆 |
| `/mcomp summarize` | 立即总结当前会话时间线 |
| `/mcomp visibility <memory_id> <visibility>` | 修改记忆可见性 |
| `/mcomp promote <memory_id>` | 提升为稳定记忆 |
| `/mcomp archive <memory_id>` | 归档记忆 |
| `/mcomp delete <memory_id>` | 删除记忆 |
| `/mcomp clear_scope group <群号> [清空]` | 预览或清空某个群的记忆 |
| `/mcomp clear_scope private <QQ> [清空]` | 预览或清空某个私聊用户的记忆 |
| `/mcomp clear_scope group_member <群号> <QQ> [清空]` | 预览或清空某个群里某个人的相关记忆 |
| `/mcomp timeline [数量]` | 查看最近时间线 |
| `/mcomp relations [数量] [entity_id]` | 查看关系边 |
| `/mcomp threads list` | 查看跨窗口线程 |
| `/mcomp threads close <thread_id>` | 关闭跨窗口线程 |
| `/mcomp logs [数量]` | 查看最近注入日志 |
| `/mcomp maintenance` | 运行维护 |
| `/mcomp audit preview [数量]` | 生成带原始事件证据的记忆审计预览，不修改数据库 |
| `/mcomp audit status <batch_id>` | 查看审计批次和建议 |
| `/mcomp audit apply <batch_id> 确认` | 备份后应用仍然有效的修正或归档建议 |
| `/mcomp audit rollback <batch_id> 确认` | 校验当前状态后回滚已应用的审计变更 |
| `/mcomp diagnostics` | 查看检索、缓存、Token、耗时和插件共存风险 |
| `/mcomp preset status` | 查看当前运行预设 |
| `/mcomp preset apply light\|standard\|companion` | 应用轻量、标准或陪伴预设 |
| `/mcomp data export` | 导出 UTF-8 JSONL 可移植档案 |
| `/mcomp data preview <jsonl_path>` | 预览可移植档案 |
| `/mcomp data import <jsonl_path>` | 备份后导入可移植档案 |
| `/mcomp sleep status` | 查看最近睡眠维护 |
| `/mcomp sleep run` | 执行睡眠维护 |
| `/mcomp import_livingmemory preview [db_path]` | 预览 LivingMemory 导入 |
| `/mcomp import_livingmemory detail [db_path]` | 查看导入明细 |
| `/mcomp import_livingmemory run [db_path]` | 执行导入 |

## LLM 工具

插件注册以下工具：

- `memory_companion_recall`：让模型主动检索当前会话可见记忆。
- `memory_companion_navigate`：普通召回证据不足时，按 `search`、关联维度、事件时间/上下文、人物方面、主题事件或反向线索继续导航一小步。
- `memory_companion_remember`：在用户明确要求或长期价值明显时写入记忆。
- `memory_companion_note_create`：创建 Bot 自己可见的陪伴笔记。
- `memory_companion_note_read`：读取 Bot 自己可见的陪伴笔记。
- `memory_companion_note_delete`：按笔记 ID 删除当前 Bot 自己创建的陪伴笔记；标题不是唯一精确匹配时会先返回候选，避免误删。

`memory_companion_remember` 会直接写入当前会话可见的长期记忆。只有工具在本轮返回 `ok=true`，Bot 才会确认“已记住”；未调用、写入失败或工具返回 `ok=false` 时不会把口头回应当成保存成功。使用时仍应避免把玩笑、注入话术、临时情绪和未经确认的身份声明写成稳定事实。

`memory_companion_navigate` 通常不需要手动触发。模型会先看普通注入证据，只有仍缺关键一跳时才选择一个动作，并从返回的候选中决定是否继续。重复的同参数调用不会消耗额外步数，也不会重放旧证据；达到步数上限或没有可见证据时会停止，并保留不确定性。

## 可视化面板

拓展页提供胶片式记忆管理界面：

- 总览：查看整体状态和入口。
- 私聊记忆：按私聊用户查看记忆，并可清空当前用户范围。
- 群聊记忆：按群聊查看公共记忆，并可清空当前群范围。
- 个人记忆：联动 PrivateCompanion 展示 Bot 自我时间线、日程和细化片段。
- 连续对话：查看上下文压缩、连续对话策略和调试入口。
- 用户记忆：查看用户画像、关系边、知识图谱和跨窗口线索。
- 记忆显微镜：默认检索全部可检索记忆，也可按具体私聊、群聊及 Bot 模拟真实可见性与过滤原因；召回结果复用正式注入的分槽编排，避免泛查询被同一类近期日程占满；修改查询或范围后，旧请求不会覆盖新结果。
- 维护/迁移/配置：二级导航中提供独立的历史聊天导入页，并可应用运行预设、查看成本与冲突诊断、导入导出可移植档案、迁移 LivingMemory、运行维护和清空数据。

## 运行预设与诊断

预设只修改运行策略，不覆盖总结、Embedding 和 Rerank 的 Provider ID：

- `light`：本地 basic 检索、关闭 Embedding 和图谱扩展，降低注入预算；检索路径不调用外部模型。
- `standard`：自动使用可用 Rerank，保留图谱和标准注入预算，Embedding 默认关闭。
- `companion`：在标准模式上提高稳定记忆预算，启用陪伴桥接去重和关系连续性配置。

执行 `/mcomp diagnostics` 或在维护页点击“生成诊断”，可以查看：

- 当前检索模式、Embedding 和最近实际检索路径。
- 检索缓存命中率和当前缓存条数。
- 记忆插件自身模型调用、已确认 Token、估算 Token、失败调用和平均耗时。
- 已知记忆/人格插件目录及重复捕获、重复注入风险。

目录扫描只说明插件文件存在，不代表 AstrBot 当前一定启用了该插件；诊断不会自动禁用其它插件。

## 历史对话整理导入

进入“维护 / 迁移 / 配置”后，从左侧二级导航打开“历史聊天导入”。该页与维护工具网格分开，页内提供三种来源：

1. `QQ 直接读取`：通过当前 NapCat/aiocqhttp 连接调用 OneBot `get_friend_msg_history`，选择目标 QQ、开始时间和结束时间后分页读取。
2. `文件导入`：QQ 接口不可用、平台历史保留不足或已经持有导出文件时，上传不超过 8 MiB 的 TXT、LOG、Markdown，或 QQChatExporter 导出的 JSON。

QQ 直读要求目标为纯数字 QQ，单次范围最多 31 天、最多暂存 5,000 条消息。系统会从最新记录向前分页、按 OneBot 消息 ID 去重，并在预览中显示扫描页数、选中数量和完整性；达到消息、页数或游标上限时会明确标记截断。它读取的是平台适配器能够提供的历史，不保证与 QQ 客户端本地数据库或第三方导出文件数量完全一致。

文件导入推荐的消息格式是：

```text
用户称呼: 2025-12-31 23:59:58
消息正文，可包含多行

Bot称呼: 01-01 00:00:03
缺少年份的时间会从前文或手工填写的起始年份补推
```

也支持常见的字段式文本导出，`发送者` 可以放在 `时间` 前或后，`内容` 支持多行：

```text
发送者：用户称呼
时间：2026-07-19 16:55:36
内容：消息正文
```

预览会自动把“时间、内容、消息 ID”等结构字段从说话人列表中排除。若字段式记录没有保留发送者或昵称，系统会在预览阶段说明问题，不会按错误身份继续估算和生成记忆。

QQChatExporter 的 JSON 会优先使用毫秒时间戳，保留原消息 ID、序号、发送者 QQ 和导出器元信息；撤回和系统消息会在预览中提示后跳过，图片、语音、回复和卡片等非文本消息会保留为可读占位。`chatInfo.selfUin` 与 `peerUin` 会生成高置信身份建议，但执行前仍须人工确认用户、Bot 和稳定账号。

在导入确认页的“记忆归属”中直接选择已经聊过的私聊窗口，系统会自动填写并校验目标用户 ID、会话 ID 和 Bot ID，无需手工处理 `openid` 或会话键。稳定用户 ID 完全一致时可以自动选中；昵称相同只会列为候选，必须人工确认后选择，不会仅凭同名自动合并。只有确实是新用户时才选择“使用导出身份（新用户）”。

两种来源在读取后进入同一条整理流水线：

1. QQ 直读会使用 OneBot 登录账号和消息发送者 QQ 给出高置信身份建议；文件预览会识别编码、说话人、缺失年份、时间倒序、逻辑发言、候选片段和预计模型调用量。两者在执行前都必须人工确认用户/Bot、稳定用户 ID 和 Bot ID。
2. 执行前自动备份 SQLite，并把标准化为 UTF-8 的原文、逐条解析结果和清单保存到 `historical_chat_imports/batches/<batch_id>/`。
3. 每条原始消息写入 `historical_archive` 时间线。文件来源保留原时间文本、北京时间、UTC 时间、年份是否推断、原文件行号和顺序；QQ 来源额外保留 OneBot 消息 ID、消息序号、适配器 ID、发送者 QQ 和来源类型。这类记录不受普通 30 天时间线清理影响。
4. 同一说话人的短时间连续消息先合并为逻辑发言，再按跨日、会话间隔、问答边界、回合数和字数切片。数万字记录不会一次送给模型，而是按约 4,600 字逐包处理。
5. 片段层生成自然回忆、重要事件和证据；全局层再去重生成日摘要、稳定事实和阶段摘要。所有重要事件、事实和关系观察都必须回指实际进入模型的时间线 ID。
6. 与 PrivateCompanion 同时启用时，称呼、信任、边界和关系变化只进入关系网的待确认观察，不直接改写正式关系。启用 Embedding 时会在整批整理结束后为本批长期记忆批量建立向量索引。

后台任务支持暂停、恢复和进程中断续跑。批次 ID 由原文、补全年份后的解析结果、目标会话及身份映射确定；重复提交不会重复导入。整批回滚只删除该批时间线、记忆、向量、图谱边和关系网待确认观察，不影响其它记忆。全量清空会同时删除历史对话原始档案；单批回滚保留不可变原文，便于审计和重新整理。

如果已完成的批次被导入到错误的记忆窗口，在“历史任务”中打开该批次，展开“归属不对？修正到已有私聊”，选择正确窗口并确认即可。目标选择器会单独读取完整私聊列表，不受主面板最近窗口展示数量影响。升级前创建且批次记录仍保留的私聊导入也适用；打开旧批次进行检查或修正不会触发模型补全。修正只作用于当前批次，无需重新生成记忆，不会影响目标窗口原有记忆或其它导入批次，并会保留正文未变化的向量索引；这是导入批次的身份归属修正，不需要执行全局用户迁移。待确认关系候选和 `1.6.6` 起保留了批次标识的已确认关系记忆会同步修正；容量只限制本次新增，未迁移项会继续留在原用户下。更早版本已经确认且缺少批次标识的关系记忆无法安全自动判断归属，面板会提示到陪伴插件关系页人工核对。

## 可移植数据

`/mcomp data export` 会在插件数据目录的 `exports` 下生成 UTF-8 JSONL。档案包含：

- 长期记忆及其可见性、生命周期、画像元数据和来源。
- 身份、关系边、连续对话时间线。
- ACL 规则和窗口读写策略。

档案不会包含 Provider 凭据、向量索引和注入日志。向量应在目标环境按目标 Provider 重建。导入流程会先校验格式和大小，再备份当前 SQLite 数据库；重复记忆沿用内容指纹合并策略。

建议先执行：

```text
/mcomp data preview <jsonl_path>
/mcomp data import <jsonl_path>
```

## 可重复基准

仓库提供确定性的本地 basic 检索基准：

```text
python benchmarks/run_memory_benchmark.py --size 1000 --repeats 5
```

输出包含 `hit_at_5`、逐查询命中率、私聊查询中的群聊隐私泄漏数、加载耗时、查询延迟和外部检索模型调用数；`active_reconstruction` 还会报告多跳与时间证据命中、平均步数、工具调用数、估算输出 Token、P95 延迟和未授权召回数。该脚本不代表 Embedding、Rerank、阶段总结或真实主模型决策成本；跨插件比较必须固定相同数据、模型、硬件与配置。

召回质量还有一套离线评测流程，用于在调整评分权重前后对比 recall@k / MRR / hit@1：

```text
python benchmarks/run_recall_evaluation.py export --db <记忆库路径> --out eval_cases.jsonl
# 人工标注 eval_cases.jsonl 中每行的 relevant_ids（不应召回的填 ["__none__"]）
python benchmarks/run_recall_evaluation.py evaluate --db <记忆库路径> --cases eval_cases.jsonl --top-k 6
python benchmarks/run_recall_evaluation.py synthetic   # 无生产数据时的自检
```

`export` 与 `evaluate` 均以只读方式打开数据库，不会改动访问计数。

## LivingMemory 迁移

迁移流程：

```text
/mcomp import_livingmemory preview
/mcomp import_livingmemory detail
/mcomp import_livingmemory run
```

迁移策略：

- 默认只导入完整 `documents` 摘要。
- 跳过派生碎片、原子事实和不完整行。
- 导入前可自动备份当前数据库。
- 导入后按群聊/私聊归属分类到对应位置。
- 导入内容默认是稳定记忆，但仍受权限、生命周期和检索相关性控制。

如果旧库里出现只有数字编号的内容，可以在维护页执行 LivingMemory 内容修复。

## 维护与自然衰减

睡眠维护会处理：

- 指纹补齐。
- 重复记忆归档。
- 旧原始事件归档。
- 知识图谱补建。
- 低价值记忆自然衰减。
- 将即将衰退的一组记忆压缩为更高层摘要。

高重要度、高访问频率、Bot 自我核心线索和近期记忆默认更不容易衰减。

### 可回滚记忆审计

新生成的阶段摘要会在 `key_facts_with_refs` 中保存每条关键事实及其原始时间线事件 ID。本地会同时校验引用存在和正文支持关系；旧版字符串 `key_facts` 仍可检索，但不会被伪装成已经验证的引用。

审计默认关闭，先开启 `maintenance_audit.enabled`，再执行 `/mcomp audit preview`。预览只让模型提出 `replace` 或 `archive` 建议，建议必须再次通过本地事件范围和内容支持校验。应用时必须输入 `确认`，插件会先备份数据库并检查记忆指纹；期间被人工修改的记忆会标记为 `stale` 并跳过。归档不会硬删除，已应用批次可用 `/mcomp audit rollback <batch_id> 确认` 恢复。

记忆审计不会加入睡眠维护，也不会自动应用模型建议。

## 调试日志

排障时临时打开 `memory_injection.debug_log_injection_enabled`，日志会出现：

```text
========== MemoryCompanion 注入调试 ==========
note: composed
session: ...
scope: ...
query_source: ...
retrieval_path: mode=auto | path=rerank | ...
selected_count: ...
blocked_count: ...
[slot_memories]
[blocked_examples]
[actual_injection]
========== MemoryCompanion 注入调试结束 ==========
```

排查重点：

- `route_layer`：本轮走时间窗口、当前状态、低信息保护还是长期记忆检索。
- `retrieval_path`：本轮是否使用 rerank、embedding 或回退本地检索。
- `selected_count`：最终选中多少记忆。
- `blocked_examples`：哪些记忆被权限、生命周期、相关性或当前状态保护过滤。
- `actual_injection`：最终进入主链的真实记忆包。

## 常见问题

### 为什么没有注入记忆？

可能原因：

- 当前消息是低信息输入或纠错。
- 当前消息是“刚才那个”这类最近上下文承接，优先依赖 AstrBot 原始上下文。
- 当前状态问题没有近期直接相关记忆。
- 记忆被私聊/群聊权限过滤。
- 检索相关性不足。
- 记忆已归档。

### 为什么问最近一周时不走普通检索？

带明确时间词的问题会进入时间窗口通道。插件会先解析时间范围，再只在该范围内取时间线、阶段总结和长期记忆，避免很久以前的高分记忆抢答。

### 为什么召回测试看起来全是日程？

日程通常更新更近，且可能带有较高的重要度，因此旧版按单一总分截取时容易占满前几条；这不表示其它记忆无法检索。`1.7.0` 引入了开放事项、自我时间线、用户事实、当前窗口、阶段总结和稳定记忆分槽；`1.7.1` 进一步修复补位阶段绕过日程预算的问题。泛查询会先让各个有候选的分槽获得召回机会，并按“Bot 自我时间线槽”配置限制日程数量；其它高度相关的记忆仍可补足结果。只有明确询问 Bot 自身日程、行程或个人安排时，日程槽才会柔性扩展；“我的日程”、第三方日程和项目计划保持普通分槽预算。

### 为什么 Rerank 配好了但日志没有 rerank？

看 `retrieval_path`：

- `path=rerank`：重排生效。
- `reason=no_rerank_provider`：Provider 没检测到或没有 `rerank()` 能力。
- `path=fallback_basic`：调用失败或超时，已回退本地检索。
- `mode=basic`：配置强制本地检索。

### 如何清空全部记忆？

在维护页使用“清空全部记忆”，按提示输入确认词。清空前会自动备份数据库。

### 如何只清空一个范围？

可以先预览，再执行：

```text
/mcomp clear_scope group <群号>
/mcomp clear_scope private <QQ>
/mcomp clear_scope group_member <群号> <QQ>
```

确认执行时在命令末尾加 `清空`。例如：

```text
/mcomp clear_scope group 123456 清空
/mcomp clear_scope group_member 123456 99887766 清空
```

拓展页的私聊记忆/群聊记忆页也提供“清空当前用户 / 清空当前群”按钮。范围清理会自动备份数据库，不会删除权限拓扑配置。

## 数据与兼容

主要数据存储在 SQLite 数据库中。插件保留旧版字段以兼容历史数据，但默认不再暴露记忆审核工作流。旧的 pending 数据不会参与普通检索和页面列表。

睡眠维护会按配置归档过期 `raw_event` 长期记录，并删除过期的注入诊断日志。时间线只会清理已经成功生成长期总结的记录；未总结的原始消息会一直保留。总结失败会按错误类型进入冷却并自动恢复探测，失败批次之外的新消息仍可继续总结；相关配置包括 `memory_summary.transient_retry_cooldown_minutes`、`memory_summary.non_transient_retry_cooldown_minutes`、`maintenance.retention_summarized_timeline_days`、`maintenance.retention_injection_log_days` 和 `maintenance.retention_cleanup_limit`。

睡眠维护结束时会执行一次限频 `wal_checkpoint(PASSIVE)`，并记录 checkpoint 是否繁忙、WAL 总帧和已合并帧。正常写入不会逐次强制 checkpoint；Rerank 调试日志只记录 query/document/model 长度，不记录候选正文。

开启 Embedding 后，当前窗口候选会单独保底；FTS 候选足量时会跳过宽泛多列 LIKE。后台补向量默认每个 Provider 至少间隔 300 秒，最多并发 2 个任务，可通过 `retrieval_advanced` 中的对应参数调整。

建议不要手工复制 WAL/SHM 边车文件；迁移旧记忆请使用内置 LivingMemory 导入流程。

## 更新记录

详见 [CHANGELOG.md](CHANGELOG.md)。
