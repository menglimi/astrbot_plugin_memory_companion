# 我会牢牢记住你

`astrbot_plugin_memory_companion` 是面向 AstrBot 陪伴体系的记忆陪伴中枢。它不把聊天记录粗暴塞回模型，而是把当前消息、连续对话、长期记忆、Bot 自我时间线、群聊/私聊权限和外部陪伴插件线索分层整理，再在每轮 LLM 请求前生成一份临时、可解释、可排查的记忆包。

- 插件名：`astrbot_plugin_memory_companion`
- 中文名：`我会牢牢记住你`
- 版本：`1.4.1`
- 适配平台：`aiocqhttp`
- AstrBot 版本：`>=4.22.0`
- 编码要求：UTF-8

## 设计目标

这个插件解决的是“Bot 如何自然地记住、想起、忘记和区分边界”。

它不会把对话记录等同于记忆。对话记录会先进入时间线，阶段性总结会把值得保留的内容沉淀为长期记忆；检索时再按当前用户消息、时间窗口、权限、召回模式和表达策略组织注入。记忆永远是当前回复的辅助资料，当前用户消息才是主任务。

与 `astrbot_plugin_private_companion` 一起使用时，推荐分工如下：

- PrivateCompanion：人格状态、日程表现、主动陪伴、环境感知、语气和生活化表达。
- MemoryCompanion：长期记忆、连续对话记忆、检索注入、权限边界、自然衰减、旧库迁移和调试日志。

## 核心能力

- 主链记忆注入：在 LLM 请求前临时注入结构化记忆包。
- 分层检索路由：低信息、纠错、当前状态、时间窗口、最近上下文和长期记忆走不同策略。
- 连续对话记忆：群聊普通发言进入时间线，通过阶段性总结沉淀为长期记忆。
- 分槽编排：自我时间线、用户画像、当前窗口、阶段总结、稳定记忆分开召回。
- 当前状态保护：例如“吃晚饭了吗”“在干嘛”只允许近期且直接相关的状态记忆进入。
- 权限隔离：私聊、群聊、自我时间线、共享记忆和内部记忆分边界管理。
- 权限拓扑：用可视化连线管理窗口间读取方向，统一处理对象级权限配置。
- 语义检索增强：支持本地检索、Embedding 候选召回和 Rerank 二阶段排序。
- 注入可观测：测试版可把检索路径、选中记忆、过滤原因和最终注入包打到日志。
- 陪伴插件桥接：可接收外部事件、去重陪伴插件上下文，避免重复注入。
- Token 可观测：独立记录阶段总结、重排、向量和维护整理的模型消耗，并可供陪伴插件 Token 页只读展示。
- LivingMemory 迁移：预览、导入、修复旧库内容，并自动区分完整摘要和碎片。
- 自然衰减：低价值、长期未访问的记忆可在睡眠维护中压缩或归档。
- 可视化面板：胶片式管理页，覆盖总览、私聊、群聊、个人记忆、用户记忆、连续对话、维护迁移和配置。

## 工作流程

每轮主链请求大致经过这些步骤：

1. 解析当前会话身份、范围、群号/用户号和真实用户消息。
2. 清理上一轮临时注入片段，避免历史 prompt 残留。
3. 判断本轮消息类型：时间窗口、最近上下文、纠错、当前状态、低信息、新话题或长期记忆检索。
4. 构造检索 query，默认只使用当前用户消息。
5. 按可见性、ACL、窗口边界和生命周期筛选候选。
6. 使用本地评分、可选 Embedding 和可选 Rerank 排序。
7. 将结果分配到自我时间线、用户画像、当前窗口、阶段总结和稳定记忆槽。
8. 按表达策略分成 `mention_memory`、`tone_memory`、`uncertain_memory`。
9. 生成临时记忆包并注入本轮请求。
10. 记录用户消息、Bot 回复和群聊普通发言到时间线，等待总结与维护。

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

## 注入包形式

注入包会明确告诉模型：

- 这是临时记忆资料，不是新的用户消息。
- 先回答 `current_user_message`。
- 记忆只在直接相关时补充。
- 与当前消息冲突时，以当前消息和用户纠正为准。
- 不要泄露其它窗口的私密内容。

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
2. 保持 `memory_summary.enabled=true`，并配置 `memory_summary.provider_id`。
3. 保持 `memory_injection.enabled=true`。
4. 检索模式使用 `retrieval.mode=auto`。
5. 初期不急着启用 Embedding；记忆变多后再配置 Embedding Provider。
6. 有 Rerank Provider 时选择对应 Provider ID，例如硅基流动的 bge reranker。
7. `context_orchestration.query_mode` 保持 `current_message`。
8. 打开 `memory_injection.debug_log_injection_enabled` 观察注入效果。

## 配置重点

### 记忆捕获

`memory_capture` 控制用户消息、Bot 回复、稳定事实和关系边的记录。当前版本不会把原话直接写成长期记忆；原始消息主要进入时间线，长期记忆由总结和明确工具写入产生。

### 阶段性总结

`memory_summary` 控制时间线压缩为长期记忆的节奏。总结输入会作为不可信消息处理，提示词注入、角色覆盖和系统指令伪装会被标记与清洗，降低总结被带偏的概率。

### 重要性评估

新记忆写入时会经过统一的重要性校准。插件会保留来源给出的基础分，再结合长期陪伴价值微调：明确要求记住、用户偏好/画像、关系变化、约定、日程、创作内容、情绪转折、阶段总结的关键事实数量和置信度都会提高分数；普通短句、寒暄、低信息原始事件会被压低。

校准结果写回 `importance`，并在 metadata 中记录 `base_importance`、`importance_evaluator` 和 `importance_source`。同时会记录拟人化维度：`persona_importance`、`relationship_weight`、`emotional_weight`、`promise_weight`、`open_loop_weight`、`emotional_debt_weight`、`creative_weight`、`preference_weight`、`self_continuity_weight`、`freshness_weight`、`scar_weight`、`last_emotional_touch_at`、`relationship_phase`、`decay_mode`、`mention_policy`、`mentionability_score` 和 `memory_reason`。

召回会轻微优先这些关系、承诺、未完成、情感债务、情绪伤痕和创作节点，但不会让硬规则压过语义相关性。“继续”“还有呢”“后来呢”这类低语义追问会优先查看 `open_loop` 槽，再走普通语义召回。普通事实会随时间逐渐降权；承诺、冲突/修复/安慰、重要创作节点会进入 `no_decay`、`scar_slow_decay` 或 `creative_milestone` 等慢衰减策略。

注入结构会按拟人化用途分区：`open_loops` 放未完成事项和承诺，`relationship_memory` 放关系线索，`emotional_context` 放情绪脉络，`creative_threads` 放创作连续性，`self_continuity` 放 Bot 自我日程与主动行为，`stable_facts` 放偏好、画像和稳定事实。每条记忆仍保留“可明说/只调语气/不确定”的用法标记。

与主动陪伴插件配合时，陪伴插件负责当前状态、即时日程、情绪底色和主动行为提示；MemoryCompanion 只补充长期解释层：为什么这个状态重要、它和用户有什么关系、过去是否有类似情境、还有什么未完成话题可以自然接上。检测到陪伴插件已注入当前状态后，MemoryCompanion 会过滤近期“当前状态复读”型记忆，只保留有关系、承诺、创作或伤痕意义的长期线索。

记忆被自然提及后，下一条用户回复会作为轻量反馈写回对应记忆：接受会提高 `mentionability_score` 和置信度；被安慰到会提高情绪权重；尴尬、否认或纠正会降低可提及性，并设置 `mention_policy=avoid_unless_asked` 或记录 `user_correction`。这样 Bot 会逐渐学习哪些旧事可以轻轻提，哪些只能当语气底色。

`mention_policy` 分为四档：

- `direct`：稳定事实或用户明确要求记住的内容，可在需要时自然明说。
- `soft_echo`：关系、承诺、创作和未完成事项，适合轻轻呼应，不要像查档案一样复述。
- `tone_only`：情绪脉络、Bot 自我状态和敏感背景，只影响语气与分寸。
- `avoid_unless_asked`：冲突伤痕、用户尴尬/否认/纠正过的内容，除非用户明确问起，否则不主动提。

### 连续对话

`conversation_memory` 记录群聊普通发言与短期上下文。它不会直接把原始窗口整段塞给主链，而是用于补全追问、判断话题变化，并在达到阈值后总结为阶段性记忆。

### 当前状态问题

“吃晚饭了吗”“在干嘛”“累不累”“今天穿什么”这类问题不会直接拉很久以前的长期记忆。插件只允许近期、直接命中当前状态锚点的记忆进入，否则会提示主链不要用旧记忆回答当前状态。

### 权限与隐私

默认边界：

- 私聊记忆默认不开放给其它窗口，需要在权限拓扑里显式连线允许。
- 群聊窗口之间按默认策略读取，具体窗口间的放行/阻止统一在权限拓扑里切换。
- 多 Bot 共用同一群聊记忆库时，Bot 第一人称阶段总结会绑定当前 Bot；其它 Bot 不会读取这类 Bot 视角记忆。
- 私聊流向群聊需要显式允许。
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
| `/mcomp sleep status` | 查看最近睡眠维护 |
| `/mcomp sleep run` | 执行睡眠维护 |
| `/mcomp import_livingmemory preview [db_path]` | 预览 LivingMemory 导入 |
| `/mcomp import_livingmemory detail [db_path]` | 查看导入明细 |
| `/mcomp import_livingmemory run [db_path]` | 执行导入 |

## LLM 工具

插件注册以下工具：

- `memory_companion_recall`：让模型主动检索当前会话可见记忆。
- `memory_companion_remember`：在用户明确要求或长期价值明显时写入记忆。
- `memory_companion_note_create`：创建 Bot 自己可见的陪伴笔记。
- `memory_companion_note_read`：读取 Bot 自己可见的陪伴笔记。

`memory_companion_remember` 会直接写入当前会话可见的长期记忆。使用时仍应避免把玩笑、注入话术、临时情绪和未经确认的身份声明写成稳定事实。

## 可视化面板

拓展页提供胶片式记忆管理界面：

- 总览：查看整体状态和入口。
- 私聊记忆：按私聊用户查看记忆，并可清空当前用户范围。
- 群聊记忆：按群聊查看公共记忆，并可清空当前群范围。
- 个人记忆：联动 PrivateCompanion 展示 Bot 自我时间线、日程和细化片段。
- 连续对话：查看上下文压缩、连续对话策略和调试入口。
- 用户记忆：查看用户画像、关系边、知识图谱和跨窗口线索。
- 维护/迁移/配置：配置检索模型、运行维护、迁移 LivingMemory、清空数据和切换主题。

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

## 调试日志

打开 `memory_injection.debug_log_injection_enabled` 后，日志会出现：

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

建议不要手工复制 WAL/SHM 边车文件；迁移旧记忆请使用内置 LivingMemory 导入流程。

## 更新记录

详见 [CHANGELOG.md](CHANGELOG.md)。
