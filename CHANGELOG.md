## 2.6.5 - 2026-11-06（Bot 经历时间线）

### 新增：Bot 自己的经历记忆
- 总结时额外产出一条 Bot 视角的脱敏经历（`self_experience`），40-80 字，只写「我做了什么、感受到什么、留下什么印象」，不写对方隐私、不复述他人原话。
- 以 `bot_self` 可见性写入 `self_action`，跨会话、跨群可见——她在群 A 经历过的事，在群 B 也能想起来。
- 开关：`memory_summary.self_experience_enabled`（默认开）、`memory_summary.self_experience_max_chars`（默认 200）。

## 2.6.4 - 2026-11-06（记忆体检修复）

### 消化链路
- 修复自动消化调度器从未启动：`_spawn_background` 的启动宽限期会把任务直接关闭，补 `defer_during_grace=True`。
- 清理孤儿批次：1,158 条 `pending/retry_pending` 没有任何原文事件，永远不可能执行，新增 `close_orphan_retry_batches()` 一次性归入 completed。
- 老会话绕过门槛：最旧超过 2 天且至少 2 条原文的会话走 `force`，不再卡在 `min_events=12`（518 个 backlog 会话里 335 个达不到门槛）。
- 修复 drain 传 `scope="unknown"` 导致窗口查询恒为空的问题（空 scope 改传空串）。
- 每轮消化顺带执行核心记忆自动沉淀，并加「自动消化跳过」诊断日志。

### 核心记忆
- 自动沉淀从 24 小时维护循环挪到消化循环（每轮都检查）。
- 同名块改为合并更新（保留最近 20 条事实），不再因 label 冲突导致永远只有第一条。
- 样本从最近 400 条扩到 1,200 条，每桶门槛从 3 条降到 2 条。

### 摘要校验
- 「摘要正文与本批原文缺乏对应」从硬错误降级为警告：只要有一个实词能在原文找到就保留本批，只有完全无依据才判编造。此前该判定直接冻结整批并重试。

### 注入
- `suppress_memory_on_low_information`、`suppress_memory_on_topic_shift` 默认改为关闭抑制：真实聊天里短句占多数，抑制会让记忆长期不出现。
- `relax_keyword_min_hits` 默认开启：查询词命中 1 个也进入候选。
- `memory_injection.top_k` 默认 4 → 8。

### 修复：待修复批次「全部放弃」不生效
- 批量释放循环把 API 返回又套了一层 `.data` 去读 `released`，读到的永远是 `undefined`，第一次请求后就 `break`，进度文案显示 0 且不再继续；`run()` 的完成提示同样读不到条数。
- 改为兼容内层/外层两种返回结构，进度按真实条数递增，完成提示显示「已放弃 N 条」。
- 后端实测：33 条隔离批次 + 655 行原文，一次 `discard` 1.01 秒完成，非性能问题。

### 面板
- 总览新增「自动消化」卡片（状态 / 上次结果 / 上次完成时间 / 最近错误），可直接跳转排队中。
- `/stats` 暴露 `summary_drain`。
- 清理 app.css 里 125 行星图残留样式（17 个类，零引用）。

### 默认值（拟人化调优）
- 记忆槽位：`self_timeline_limit` 2→4、`conversation_summary_limit` 2→3、`stable_memory_limit` 3→4、`persona_memory.max_items` 4→6。
- 核心记忆：`max_blocks` 8→12、`max_chars` 800→1200、`auto_distill_max_blocks` 3→6。
- 总结节奏：`min_events` 12→8、`trigger_event_count` 12→8。
- 画像：`daily_success_limit_per_person` 1→3、`daily_attempt_limit_per_person` 2→6、`min_independent_evidence` 3→2。
- 注入单条 320→240 字：条数更多、每条更短，更像人嘴里的细节。
- 衰减分阈值 75→65：在乎的人淡得慢一点。
- 跨窗口衔接 30→120 分钟；细节清晰期 45→30 天（近一个月的事记得清）。
- 同步 `core/operations.py` 三档预设与 `core/service.py` 运行时兜底；`DEFAULT_CORE_MEMORY_CHARS` 800→1200、`DEFAULT_MAX_ITEM_CHARS` 320→240。

### 批次视图拆分
- 「导入」下拆成三个独立入口：**待修复批次**（quarantined，可逐条 / 整批重新排队或放弃）、**排队处理**（pending，只读）、**已处理批次**（completed + no_memory，只读，标注「已总结 / 无新增记忆」）。
- 总览三个 KPI（待处理批次 / 待修复批次 / 已处理无新增记忆）分别跳到对应视图，不再挤在同一个页面里。
- 后端新增 `list_processed_batches()` 与 `/maintenance/summary_batches?state=processed`；缓存串升到 `2.6.2.5`。

# Changelog

本项目遵循面向用户体验的版本记录。日期使用北京时间。

## 2.6.3 - 2026-11-06

> 修消化（记忆真正记得住）+ 注入增强 + 跨群「一个人的记忆」+ 自动沉淀。

### 消化链路：新增全局积压消化
- 以前只有「这个会话来新消息」才会触发总结，老会话的原文会一直躺在 timeline 里没人处理。
  现在新增后台消化调度：启动后延迟 120 秒开始，每 10 分钟扫一轮，把「未总结且没有排队批次」的会话
  按最老优先补上总结，每轮最多 5 个会话（`memory_summary.auto_drain_*`）。
- 清理「孤儿批次」：没有任何原文事件的 pending/retry 批次直接归档为 completed，不再占着「待处理」的数字。
- 实测基线：未总结原文 28,078 条，其中 20,506 条从未被分配批次；孤儿 retry 批次 1,158 条。新调度会逐步消化。

### 注入增强
- `memory_injection.top_k` 默认 4 → 8；长问题（40 字以上或含多个问号）自动 +2（上限 20），
  时间类问题保持更宽的召回。
- `retrieval_advanced.dedupe_content_ratio` 默认 0.0 → 0.85：内容高度相似的记忆在注入前合并，省上下文。
- `memory_summary.min_events` 20→12、`trigger_event_count` 20→12、`trigger_interval_minutes` 60→30：
  更早开始总结，不用攒一大坨。

### 跨群「一个人的记忆」
- 同一个人在 A 群说过的话，本人在 B 群时也能被回忆起（`same_person_other_group`）；
  别人的群公开记忆仍然不可见，隐私边界不变。
- `visibility.allow_group_public_in_private` 默认 False → True：私聊里可以带出群聊公开记忆（可在配置里关）。

### 自动沉淀
- 维护任务每轮从高重要度的长期记忆里挑事实，补成核心记忆块（默认最多 3 块，不覆盖你手写的块）。
- 新增配置：`core_memory.auto_distill_enabled` / `auto_distill_max_blocks` / `auto_distill_min_salience`。

### private_companion v2 联动
- 向 private_companion 7.x 的 `_private_companion_memory_providers` 注册表注册外部记忆 provider
  （协议 `companion.external-memory.v1`，声明 `handles_model_memory=False`）：
  私聊回复前它会调用本插件的 read 召回记忆并注入「【外部记忆参考】」，记忆面板的 summary 统计也走本插件。
- 注册在插件启动后后台重试，private_companion 比本插件晚加载也能接上；插件停止时自动注销。
- 原来的 v1 探测（`get_memory_companion_bridge()`）保持不变，两条路互不冲突。

## 2.6.2 - 2026-11-06（本地补丁）

> 删掉三维终端面板，控制台显示优化。

### 删除三维终端
- `modern.html` 的三维场景移除，改成跳转到控制台（旧配置/缓存打开也不 404）。
- 删除 `assets/index-URVgTPOQ.js`、`assets/index-CWNk7gDr.css`、`fonts/`（4 个 MiSans 字体约 19 MB）、
  `archives/`（80 个死数据 txt）、`injection-status.css/js`、`summary-status.js`。
- 保留 `assets/*.glb` 与 `cinema-3d.bundle.js`，控制台的终端模式仍可用。
- 默认 `appearance.ui_style` 回到「控制台」。

### 控制台显示优化
- 配色首帧缓存：`appearance.theme` 对应的 palette 写入 localStorage，刷新/重载不再闪默认紫。
- 深浅切换加 0.3s 过渡（`prefers-reduced-motion` 下关闭）。
- 移动端（≤640px）：导航改底部条、子菜单浮层、抽屉全宽、卡片单列、顶栏紧凑。
- 卡片/KPI/列表 hover 与抽屉滚动条细节打磨。

### 总览 KPI
- 11 个总览指标卡换成渐变描边卡：图标、色调光晕、渐变数字、悬停抬升、入场阶梯动画。
- 每张卡可直接点击跳转：记忆总量/私聊/群聊/原文/会话记忆 → 记忆库对应筛选，用户档案 → 用户档案，
  核心记忆 → 核心记忆，开放线程 → 导航，待处理/待修复/已处理 → 待复核区。

### 知识星图：删除
- 「知识星图」视图整块移除（导航入口、总览入口、画布代码约 49 KB）。总览的「时间线事件 / 关系边」
  两张卡改为跳转到记忆库，不再指向星图。

### 面板细节
- 核心记忆：每个块可「删除此块」，二次确认后调 `/core-memory/delete`，删完刷新列表。
- 待修复批次：单条重试/丢弃的忙碌动画最短 3 秒，慢设备上也能看清状态再跳转；「全部重新排队 / 全部放弃」改成分批执行（每批 10 条），忙碌层实时显示「已放弃 x / y」「已重新排队 x / y」，不再一次请求干等。
- 待修复批次分两个页签：「待修复」（隔离失败，可重试 / 放弃）与「排队中」（正常排队等总结的批次，只读），
  避免把「待处理 400 条」误当成 17 条故障。
- 「放弃」现在是真删：连批次持有的原文事件一起从 timeline 物理删除（DELETE 会触发 FTS 索引与
  tombstone 清理），不再只标记 summarized_at、把原文留在库里占空间。
- 总览 KPI 口径澄清：「待处理批次」= 正常排队等总结的批次（不是错误），「待修复批次」= 总结失败被隔离的批次（冻结原文 x 条），避免两者被误读成同一个数。
- 总览新增「Bot 记忆分布」：按归属 Bot 分块，显示 Bot 名字（取自人格设定）与记忆条数，点名字直接进记忆库并按该 Bot 过滤；未标记归属的旧数据显示「未标记归属」。
- 记忆检视顶部新增 Bot 分区条：「全部 Bot」+ 每个 Bot 名字·条数，点一下只看这个 Bot 的记忆。
- 页面资源版本串升到 `?v=2.6.2.2`，强制浏览器拉新脚本，避免旧缓存让改动看起来「没生效」。
- 人物页：卡片从大方块改成横向圆润条块，头像 36px、摘要一行，一屏能看更多人。
- 历史聊天：QQ 号预览失败或没读到消息时给出明确提示（号填错 / 时间范围没覆盖 / 连接不支持），不再静默。
- 最近注入日志：每条记忆标出「私聊· / 群聊· / 档案· / Bot·」，跨窗口注入标「↔跨窗口」，
  便于确认群聊与私聊之间的记忆互传。

### 核心记忆
- 核心记忆卡片新增「从记忆提炼核心块」：把现有记忆按私聊 / 群聊 / 档案 / 全局各汇总成一条候选块，
  确认后批量写入，之后可在列表里逐条改或删。核心块本身不会自动生成，空库时面板会提示先聊几轮。

### 配置面板
- 每个模块只把最常用的几项摆在明面，其余收进「高级项（N 个）· 一般不用改」折叠，避免一屏几十个输入框。
- 完整配置仍在 AstrBot 插件配置页，两边改同一份配置。

### 群聊记忆补全
- `conversation_memory.capture_group_messages` 默认值从「关闭」改为「开启」：群聊里 @ 机器人、
  回复机器人或命中关键词的发言会写入记忆，私聊时才有素材想起群里聊过的事；群聊普通闲聊仍不记录。
- 本机配置同时把 `scope_control.group_capture_enabled` 打开（原来关着，等于群聊完全不捕获）。
- 想让私聊直接看到群里的公开记忆，还需在「隔离与可见性」里打开「私聊可见群公共记忆」
  （`visibility.allow_group_public_in_private`，默认关闭，属隐私项，本次未擅自改）。

## 2.6.1 - 2026-10-30（本地补丁，非上游；娜莉灵 修改）

> 这一版没有新功能。它把 2.6.0 复核报告里剩下的 48 条（25 条「没修」+ 23 条「只修了一半」）逐条修掉，
> 并且每一条都配了回归测试。下面按「她自己的行为」分组，技术编号在括号里，方便对照报告。

### 她会「真的忘」也能「真的想起来」
- **召回不再被假信号带偏**：词频改成真 BM25（饱和 + 文档长度归一化），空查询不再靠重要度硬凑，
  停用词表里的评测句子碎片清掉，同会话/同群那点硬加分从 +0.25 压到 +0.05，冗余惩罚从 0.16 提到 0.35，
  人工锚定默认关闭（R1/R2/R3/R6/R7/R5）。
- **注入预算按价值分配**：预算不够时先装最该装的，而不是先到先得；注入里不再回显「检索模式/检索关键词/Bot 心理能量」
  这类内部字段（诊断开关打开时才回显）；四处互相打架的字数上限收敛成一套常量（R10/R12/R13）。
- **重要度不再靠硬编码词表**：9 个维度、6 组标记、权重全部外置到 `core/lexicon/importance_lexicon.json`，
  部署方可以直接改词表不用发版；核心记忆不再同时把 importance 抄成 salience 算两遍（S6/S7）。

### 她有自己的情绪状态，而且情绪真的影响想起什么
- 新增 `core/emotion_state.py`：valence / arousal / debt 三轴，按半衰期（3h / 2h / 12h）自然衰减，
  被事件按强度×置信度 EMA 更新；只读现有 `emotion_events`，不新建表、不改老库（H10）。
- `core/affect_modulation.py` 从「空壳 DTO」变成真调制器：输出检索倍率（夹 0.7–1.6）、
  未了债务跟进加成（夹 0–0.35）和五档语气（calm/warm/bright/low/tense），并已接进检索排序——
  同等相关度下，欠着的话、正在气头上的事会被轻微抬起，心情好时旧事更容易浮上来（H10/H11）。
- **人的分量不再靠关键词计数**：不再用 `content LIKE '%吵架%'` 这种词表数「吵过几次架」，
  改成读真实记忆与情绪事件（近期、耐久、情绪权重加权）算证据分；旧数据没有证据包时行为与 2.6.0 完全一致（H2）。
- **刻骨铭心不再「一句亲密话就中」**：需要两个独立信号（亲密 + 承诺/里程碑，或亲密 + 冲突 + 强类型）（S9）。

### 存储：读写分离、扫描走索引、擦就是擦干净
- 读路径不再抢写锁：`_list_memories_sync` 走只读连接（主连接有未提交事务时回退，保证读己之写）（S1）。
- 时间线引用扫描从「全表 + 逐行 JSON 解析」改成生成列 + 部分索引，`EXPLAIN` 确认走索引（S5）。
- `memories` 的 bot 归属判定收敛到一处（`_bot_scope_clause`，含列名白名单），不再九处 `OR bot_id=''` 兜底（S13）。
- 归档/可召回判定收敛到 `_recallable_memory_sql` 一处；生成列迁移改成幂等（`PRAGMA table_xinfo`，
  生成列在 `table_info` 里根本看不到——这是上一版会炸库的坑）（S4）。
- 擦除补齐三个窄口：知识图谱节点/边、纠错回执、注入日志的 user_id/bot_id（P0-2）。
- 人卡可见性不再自己另起一套：复用检索同一套 ACL 预过滤（L14）。
- 删掉 390 行从没被引用过的 `core/migration_outbox.py` 和只在它上面跑的测试（S12）。
- 删掉 `_initialize_database_sync` 的重复定义（H12）。
- 账本损坏不再假装正常：`provenance_store` 解析失败返回 `state=corrupt` / `ok=False`，
  并且后续写入不会覆盖掉损坏的账本文件（P11）。

### 面板与命令：该拦的拦住，该给的给到
- `/config/module/update` 现在拒绝改安全键（ACL、桥接闸门、擦除开关等），返回 403 `protected_config_key`（P8）。
- 所有写/危险路由统一走 `_wrap_route`：先 CSRF（`GET /ui/csrf` 发 token，TTL 900s）再 dashboard admin（P7/P13）。
- 危险确认从「公开固定串」改成一次性 nonce（`POST /ui/confirm-nonce`，24 位 hex，TTL 120s 用后作废）（P9）。
- 审计送模型的正文改成脱敏投影：480 字截断、去邮箱/URL/@提及/长数字，evidence 240 字（P10）。
- livingmemory 的 `?path=` 与导入入口全部走路径白名单（禁 `..`、resolve 后必须落在 data 目录或其父目录）（P4/P5）。
- 只读命令（status/search/explain/recent/timeline/relations/logs/diagnostics/help）普通成员可用，
  其余仍是管理员；`delete` 要二次确认（120 秒内再说一次「确认」）（A10）。
- 桥接写入口（`record_external_memory` / `provenance_*` / `mark_visibility`）要求 producer capability；
  严格模式跟随既有 `private_companion_bridge.enable_p5_b1_bridge_gate` 开关（默认关，避免打断已在用的外部插件）（A11）。
- 插件卸载时主动反注册 web 路由（宿主 `_unbind_plugin` 不清路由，之前会留下打到已关 store 的僵尸路由）（A6）。

### 宿主兼容
- 私聊也有采集入口了（之前只注册群消息）；群聊默认不采集，只在被 @/回复/唤醒前缀/关键词时才记（A1/A2）。
- `tool_query` 的 `parameters` 接受 dict / JSON 字符串 / None，非法输入明确报 `invalid_query_arguments`（A12）。
- `metadata.yaml` 的 `astrbot_version` 从没有依据的 `>=4.22.0` 改成 `>=4.27,<5`（A13）。
- 删掉 `astrbot_compat.manage_request_contexts` 死码，TextPart 解析收敛成单点（A5/A14）。

### 配置
- 补齐 6 个原来「代码在读、schema 里没有」的键：`source_semantic.query_max_chars` / `documents_per_query`（L3）、
  `retrieval_advanced.anchor_floor_enabled` / `scope_bonus_scale` / `mmr_redundancy_weight`、
  `context_orchestration.include_intent_diagnostics`。

### 测试
- 新增回归：`tests/test_fix_retrieval_injection.py`、`test_fix_emotion.py`、`test_fix_emotion_tier.py`、
  `test_fix_emotion_wiring.py`、`test_fix_api.py`、`test_fix_panel_{security,bridge,commands,operations,audit}.py`、
  `test_fix_main_wiring.py`、`test_fix_message_capture.py`、`test_fix_person_weight_evidence.py`、
  `test_fix_bot_scope.py`、`test_fix_store_scan.py`、`test_fix_store_read_path.py`、`test_fix_erase_residue.py`、
  `test_fix_person_card_visibility.py`、`test_fix_database_init.py`。
- 全量：1624 passed / 4 skipped / 454 subtests（884.54s，EXIT=0）。


## 2.6.0 - 2026-10-30（本地补丁，非上游；娜莉灵 修改）

### 为什么有这一版

上一版被一份严格审核打到 38/100。逐条复核后：有一处是误判（跨群召回已撤回，不算缺陷），有几处是夸大（「渐进遗忘」不是宣传语，只是阈值太松、实际上很少触发），但大部分是真的——写进 README 和 CHANGELOG 的能力里，有些是死码、有些从未触发、有些只在测试里成立。这一版不加功能，只把「写下来的」变成「真跑得起来的」。

### 她真的会忘（不再只是写在文档里）

以前「渐进遗忘」只有一步：衰减分数过线就直接归档，不够就永远不动，老事再久也进不了候选池。现在分两步：

- **先褪色再归档**：`store.fade_memories` 按比例压 salience，并在 `metadata` 里记 `fade_level`/`faded_at`（同一档至少隔一天），降到地板以下才进归档；`_run_memory_decay` 返回 `faded`/`fade_held`，说明这轮褪了几条、压住了几条。
- **被想起会回一点**：注入/访问时抬 `reinforcement_score` 与 salience（不进 `retrieval_revision`，避免每轮注入让快照抖动）。
- **打分侧真的能压下去**：`core/memory_lifecycle.py` 的新鲜度乘数从「最多扣 35%」改成 `0.22 + 0.78 * decay_factor`，半衰期到了只剩两成多；salience 加成也随衰减同步收。
- **新增四个开关**（`maintenance_decay.memory_decay_gradual_enabled` 默认开、`fade_floor_percent` 25、`fade_ratio_percent` 70、`fade_interval_days` 1），并补上 `maintenance.memory_decay_*` 到新前缀的别名——上一版这四个控件是死的。

### 删除真的删干净（被遗忘权）

- 新增 `store.delete_memory_cascade` / `delete_memory_report` / `erase_person_data`：删一条记忆会连带清理 `review_queue`、`memory_embeddings`、`relationship_edges`、`knowledge_edges`、`life_source_watches`、`chat_import_segments` 与 `summary_batches` 的引用、fts、注入日志里的 id（只摘 id，不删日志）、无人引用的 scoped timeline；`erase_person_data` 按人整体擦除（memories 级联、timeline、批次事件、身份、分量、墓碑、导入批次、情绪事件、画像七表、injection_logs）。
- 面板新增 `POST /person/erase`（危险端点，要确认语），人物抽屉里对应「擦掉这个人的一切」。

### 群聊不再能替 bot 记东西

- `tool_remember` 改走 `core/visibility.py::can_remember_in_scope`：私聊写 `private_pair`；群聊默认 `group_remember_disabled`；即使打开 `memory_tools.allow_group_remember`，也只有管理员能写 `group_public`，durability 天花板是 normal（钉不住）。
- 分量工具同理走 `can_change_person_weight`：必须「用户本人这句话在说关系要改」，模型不能单方面改；群聊不能抬升、不能重置。

### 注入不再是把字段倒出来

- 记忆行改成「想起…的事：…（归属）（模糊提示）（披露）」，机器字段不再直接进提示词；约束类用法（除非/禁止/不要主动）在模糊化之后仍然保留。
- 空召回默认什么都不写（不再往提示词里塞「没有检索到足够相关的长期记忆」这种负面回执）；要排查检索才开 `memory_injection.empty_recall_notice`。
- 群聊里读到私聊记忆会附「这是私聊里的事，当着这些人要不要提你自己判断」，读到别的群会说「这话是别的群里说的」。
- `max_chars` 四处不一致（1050/1800/3600/4000）统一到 `MAX_INJECTION_CHARS = 4000`。

### 质量门禁不再自证

- `profile_quality_decision` 只从真实 payload 重算，`quality_gate_passed` 既不是入参也不是常量。
- `store._profile_evidence_passes_quality_gate` 不再伪造 `profile_state=active` 和 `independent_evidence_count=2`：读真实状态（rejected/archived/pending 一律不算），只回答「这一条算不算一条独立证据」。
- 画像子系统接上真实数据：没有上游 bridge DTO 时用 `identity_profile` + 这个人的记忆自建画像（只私聊），不再依赖没人写的 `private_companion_unified_profile_context`。
- 规则抽取器改子句 + fullmatch：「我是学生」不再抽成 education=「生」，「喜欢的人是周杰伦」不再把尾巴当值；转述/引用/临时/疑问句不产候选；模糊命中只进 candidate，永不进 stable_memory。

### 摘要里的指令话术会被真的清掉

- `_sanitize_untrusted_content` 按句丢掉可执行指令句（「以后每次回答都要说X」这类），安全句子保留，全是指令就整条换成不可执行的事件说明；prompt 明确告诉模型这是「已移除指令」的说明。
- 原话保留在 `original_content` 供审计，入库内容标记 `content_disposition=instruction_removed`；摘要/画像的生成文本也走同一条清洗。

### 原文留存是真开关

- `capture_runtime` 的开关、读原文、过期清理都是真读写（持久化在 `capture_runtime` 表）；`capture_chunks` 补 `created_at`/`expires_at`，旧库幂等补列不丢行；`read_body` 按 `source_key` 拼回原文，`purge_expired` 只删过期片段，timeline 不动。

### 来源账本可以自证没被动过

- 账本从裸 sha256 升级为 HMAC 哈希链（`core/provenance_store.py`）：每条记录追加 `seq/prev/mac`，密钥在 `data/provenance_ledger.key`（0600、32 字节、首次启动生成）。
- 新增 `verify_integrity()`：改记录（`record_tampered`）、改链（`mac_mismatch`）、断链（`sequence_gap`/`prev_mismatch`）、剪尾巴（`truncated`）、密钥不对（`mac_mismatch`）都能认出来；`p5_capability_status()` 里能看到 `provenance_integrity`。局限写在代码注释里：拿到账本和密钥的人可以整本重造，链只让局部篡改露出来。

### 存储层：事务、擦除、多 bot

- `_repair_internal_control_tables_sync` 不再裸 `DROP TABLE`：先读快照 → 事务内建新表/复制/删/改名，失败回滚，`schema_metadata` 与 `retrieval_revision` 有恢复路径（revision 只增不减）。
- `scoped_store` 的擦除按 `namespace_scope` 里的 persona/group/identity 精确匹配，不再靠 `record_id LIKE` 前缀；新增 `erased` 列（幂等补列），重新学习时归 0。
- `timeline` 加 `bot_id` 并从 `metadata.owner_bot_id` 回填，读取接口按 bot 过滤，多 bot 时间线不再混。

### 检索与召回

- 去重时高分项不再被挪到队尾丢掉（原地替换）。
- 候选池不再只按时间取：重要度一半 + 最近一半的并集，并过滤 archived/superseded/expired，几千条记忆时也不会把七成记忆永远挡在门外。
- 跨会话去重真的会命中同一句话，但不再误合并：带幂等键的（bot 自我记忆、外部写入）、画像/偏好/习惯类、带 `extractor`/`source_memory_id` 的一律不合并。

### 配置、打包与面板安全

- 删死键 `memory_injection.injection_cache_ttl_seconds` 与悬空别名，补 `maintenance.memory_decay_*` 别名；`retention_unsummarized_timeline_days` 默认 0 → 365；`request_max_retries` 从写死 1 改为可配、默认 2；`clean_proactive_history` 默认关（只清自家残留）。
- 新增 `requirements.txt`/`requirements-dev.txt`/`pyproject.toml`/`tests/conftest.py`/`scripts/check_release.py`/`.gitignore`（`data/`、`__pycache__`），CI 增加发布前自检。
- 面板路由分三档（read/write/dangerous），危险端点必须带确认语；`/memories` 必须带 `scope` 或 `entity_id`，limit 有上限，evidence 默认隐藏；页面请求写 `page_access.log` 并轮转；插件卸载后页面接口返回 503。

### 测试

- 本版新增/更新：`test_report_fixes_260.py`(18)、`test_provenance_integrity.py`(7)、`test_store_repair_atomic.py`(3)、`test_scoped_erase_real_owner.py`(3)、`test_multi_bot_isolation.py`(6)、`test_profile_extraction_h9_h8.py`(16)、`test_portrait_self_built_h7.py`(4)、`test_source_capture_lifecycle_p1.py`(4)、`test_injection_defense_p2.py`(8)、`test_write_scope_guard_p3_h6.py`(27)、`test_panel_guard.py`(19)、`test_release_hygiene.py`。
- 全量套件：**1405 passed / 3 skipped / 409 subtests**（778.76s，Python 3.12 + 宿主 astrbot 4.27.3；上一版为 1259 passed）。

### 兼容性

- 只新增表/列/端点，不删不改既有 `memories` 结构与正文；旧库升级自动补列、补档、补分量，一条不丢（真实库 445 MB / 7724 行回放：行数不变，正文与时间戳哈希前后一致）。

### 测试基线

- 全量：1405 passed / 3 skipped / 409 subtests（778.76s）。
- 定向回归：`-k "candidate_bundle or store_consistency or recall_scoring or person_card or person_wiring or lifecycle or visibility or memory_tier or c3_bot_personal or reply_continuity"` 144 passed；`profile or portrait or capture or summarizer or quality or injection_defense` 191 passed；`store_consistency or scoped or timeline or isolation or c3_bot_personal or private_group_acl_recall` 124 passed。

## 2.5.0 - 2026-10-30（本地补丁，非上游；娜莉灵 修改）

### 打开就是「她记得的人」

以前打开拓展页先看到一堆统计和开关，得自己找人在哪。现在第一眼就是一张张人物卡：她记得谁、怎么称呼、什么关系、这个人对她多重、最近记得的几件事。点开一张卡就能改称呼/关系/备注、把分量往上往下挪，或者让她把某件事放轻。

- **人物卡首页**（`pages/记忆面板/people.html` `people.css` `people.js`）：搜索名字/称呼/关系，按分量/最近说话/记得多少排序，多 bot 可筛；卡片显示档位、称呼、关系、「N 件事 · M 件刻骨」与两件最牢的话。
- **单人抽屉**：分量滑杆 0–100（旁边写人话档位）、称呼/关系/备注三个框、记忆列表；每条可「让她忘掉这条」——只是放轻（durability 转 short），原文还在库里，不是删除。
- **入口三分支**：`appearance.ui_style` 选「人物」进新面板，「控制台」还是旧的全部功能页（`legacy.html`），「三维终端」是彩蛋（`modern.html`）。老配置值 `modern`/`新版`/`legacy`/`旧版` 继续认，不会因为升级打不开。
- **新端点**：`GET /people`（目录）、`GET /person`（单人详情）、`POST /person/weight`（改分量/称呼/关系）。都登记为 internal，不出现在旧面板的可见视图列表里。

### 开箱即用的默认值

装上别急着翻配置，默认就是能用的样子：

- `appearance.ui_style` 默认「人物」；
- `persona_memory.enabled`/`weight_enabled`/`absorb_enabled`、`retrieval.embedding_enabled`、`memory_humanization.enabled`、`memory_tools.*` 默认开；
- 历史导入、外部插件联动这类重功能仍默认关（要自己点，避免装完就翻旧账）。
- 没有嵌入模型也不会报错：自动退回全文检索；旧库首次启动自动补一次「旧记忆轻重」，并按已有记忆把每个人的分量先算好——打开面板就能看到人，不用等下一句话。全程不改正文、不删行。

### 描述重写

`metadata.yaml` 的 description/desc 与 README 顶部改成说人话：她是干什么的、第一次装上要做什么（什么都不用做）、面板能干什么、想细调再翻文档。

### 测试

- 新增 `tests/test_people_panel.py`（15 例：目录排序/搜索/多 bot 隔离/空库、单人详情与条数上限、旧库首次升级先算好分量、`/people` `/person` `/person/weight` 实测、默认面板分流、前端资源与路由登记）。
- 全量套件 1259 passed / 2 skipped / 186 subtests（2.4.0 基线 1244）。

### 兼容性

- 只新增前端资源与三个只读/写档案端点，不改 `memories` 结构与老页面；旧的面板地址与配置值继续可用。
- `modern.html` 里 `summary-status.js` 的缓存串从上游遗留的 `2.1.4` 拉到 `2.5.0`，页面静态资源版本统一。

## 2.4.0 - 2026-10-30（本地补丁，非上游；娜莉灵 修改）

### 她心里有杆秤：分量

记忆该留多久，不该由全局参数替每个人决定——「这个人对我重不重要」才是。这一版给每个用户一份分量（`core/person_weight.py`），决定她想起多少、忘得多快。

- **怎么掂**：四块合计 0–100——留下多少（广度，0–25）、留下多深（刻骨/要紧的条数，0–35）、认识多久与多少个日子说过话（时间，0–20）、一起经历过什么（冲突与承诺，0–20）。久不来只软化最多到八五折，不会归零；有过记忆的人最低 1 分。
- **六档人话**：路过的人（0–9）、认识的人（10–24）、熟人（25–44）、亲近的人（45–64）、很重要的人（65–84）、刻骨的人（85 以上）。卡片上只说「什么人」，不念数字。
- **别人说了就听别人的**：人形化/关系插件在请求里报了好感度与关系阶段，就用它的值（`merge_external_weight`）；没人报才自己掂量，群聊里也照样知道这个人多重。
- **按人遗忘**：衰减候选的年龄/闲置倍率乘以这个人的分量系数（0.55–2.4），在乎的人慢一点，路过的人快一点。仍然只是「变淡/归档」，不删行。
- **她能改口**：新增工具 `memory_companion_person_weight`（get / set / reset）。用户本人说「我们没那么熟」「别叫这么亲」，模型可以把它挪下去；用户亲口定的关系比任何自动值都硬，不会被下次自动刷新冲掉。群聊里改了也只影响当前发言者对这一个 bot。

### 顺手记住别处说的关系（不写记忆）

关系插件（如 `user_tag`）会在请求里说明「她在这人面前是谁」，格式是一段 `<relation>` 文本。新增 `core/absorb.py`：只解析「我在X面前就是Y」这种视角句，把关系名、称呼、备注写进这个人的档案（`identities.profile`），**不写进 `memories`、不当事实讲、不进历史检索**；用户本人亲口说过的关系带 `relation_source=user`，上下文来的永远盖不掉它。开关 `persona_memory.absorb_enabled`，默认开。

### 摘要按人写（叙事落在人身上）

以前一段对话总结出来是「发生了什么」，读的人分不清哪件事是谁的。现在总结提示词要求：同一批里每个人的事贴回每个人自己身上，用原文里的昵称或稳定 ID，不混成「大家」「有人」；谁第一次说出自己的称呼、关系或身份，连原话和日期一起留下；Bot 自己的事写在她自己身上，不算到用户头上。只改写作要求，不改总结产物的数据结构与检索路径。

### 配置

- `persona_memory.weight_enabled`（默认开）、`persona_memory.absorb_enabled`（默认开）、`memory_tools.enable_person_weight_tool`（默认开）。全部关掉即回到 2.3.7 行为。

### 测试

- 新增 `tests/test_person_weight.py`（14 例：分量数学、档位、缓存、纠正、不同 bot 各算各的）。
- 新增 `tests/test_external_absorption.py`（20 例：只认视角句、去重、用户来源优先、不改入参）。
- 新增 `tests/test_memory_person_wiring.py`（13 例：吸收写档案、纠正入口、人卡按场合、群聊也有分量、按人衰减）。
- 新增 `tests/test_summary_person_narrative.py`（2 例：提示词要求按人分开写、材料里保留说话人与稳定 ID）。
- 全量套件 1244 passed / 2 skipped / 186 subtests（2.3.7 基线 1195）。

### 兼容性

- 顺手修齐：`modern.html` 里 `summary-status.js` 的缓存串从上游遗留的 `2.1.4` 拉到 `2.4.0`，现在页面所有静态资源版本一致；`.gitignore` 忽略跑测试时宿主生成的 `data/` 目录。
- 只新增 `person_weights` 表（`CREATE TABLE IF NOT EXISTS`），不改 `memories` 结构、不删行、不改正文；旧库首次启动自动建表。
- 分量为空或表不存在时按普通处理，不阻塞注入与衰减。

## 2.3.7 - 2026-10-30（本地补丁，非上游；娜莉灵 修改）

### 记得这个人：从「记消息」转向「记人」

先用真实库做过一次体检：567 个认识的用户里只有 132 个在 `memories` 里有对应条目，八成记忆是会话摘要，重要度有 68% 挤在 0.8–0.9（等于没有轻重），`relationship_edges` 只有群成员关系、没有任何「恋人/朋友」类边。也就是说——它记住了很多话说，却没记住说话的人。这一版补三件事，全部作用于写入与注入两侧，不改既有召回/权限/生命周期判定。

- **人物卡（`core/person_card.py`、`core/service.py::_compose_person_card_block`）**：每轮注入前先拼一块 `<person_memory>` 区块——`identities` 里的显示名/别名/画像 + 用户偏好的称呼 + 关系阶段与好感分（来自 `SessionContext`，即人形化插件提供的值，本插件只读不自算）+ 该用户按「刻骨 > 记得 > 印象、重要度、时间」排序的前 N 件事。默认 420 字上限、4 条锚点、每条 90 字，超预算按「减条数 → 缩单条 → 只留抬头 → 硬截断」逐层降级，保证任何情况下都不会挤掉主记忆注入。块本身不进 `included_memory_ids`，不参与注入强化计数。配置项 `persona_memory.enabled / max_chars / max_items / max_item_chars`，schema 默认开。
- **刻骨记忆保留原文（`core/memory_tier.py`）**：新增写入期分层——`imprint`（亲密≥2 个不同说法、强记忆类型+亲密、承诺≥3、里程碑+承诺或强类型、冲突≥2+强类型，或有 `manual/protected/keep/no_decay` 标签）、`important`（强记忆类型、承诺≥2、里程碑≥2 或里程碑+冲突）、`normal`，结果写进 `metadata.memory_tier` 并抬升 `durability`（pinned/durable/normal，只升不降）。分层挂在唯一写入漏斗 `_insert_memory_sync` 里，所有记忆类型自动获得档位。
- **不拿重要度当轻重**：真实库 68% 的行挤在 0.8–0.9，用 `importance` 抬档等于所有记忆一样重，因此 `importance` 不再参与档位判断（只保留给人看的显示分）。同时命中词去重——「上床」不会连带「床」算两次，一个词钉不住一条摘要。
- **旧数据补一次档（`core/store.py::_backfill_memory_tier_sync`）**：升级后首次启动扫描 `durability` 仍为 normal/short/ephemeral 的旧行，够刻骨的补 `pinned`、够要紧的补 `durable`，正文一个字不改、一行不删；分块提交（每块 500 行）并用 `schema_metadata` 存游标，几十万行也不会卡住启动，失败只警告下次再试。真实库（7724 行、445 MB）回放结果：只上调 294 行（`pinned` 665→778，`durable` 2860→3041），正文与时间戳的哈希前后一致、行数不变，其余照原来衰减。
- **嵌入召回默认开（`retrieval.embedding_enabled`）**：默认值 false→true——没有它，召回只能靠字面相似，等于还是消息记录库。没配嵌入模型不报错：`core/retrieval.py` 直接返回空向量候选（reason=no_embedding_provider），回填只在 provider 解析成功时调度，未发现 provider 只警告一次。
- **归档豁免（`core/store.py::archive_raw_events_older_than`）**：原始事件 30 天归档原本会连亲密内容与承诺一起扫走。现在 `protect_imprint=True`（默认）时，SQL 层排除 `durability in ('pinned','durable')`，逐行再用 `is_protected_from_retention` 复核 `metadata.memory_tier` 与保护标签，命中即跳过。配置 `persona_memory.imprint_keep_forever`，默认开；关掉则回到旧行为。
- **两个 bot 是两个人**：`store.person_snapshot(user_id, platform, bot_id, limit, scope, group_id)` 的身份与记忆查询都带 bot 维度（`owner_bot_id=? OR owner_bot_id=''`），人物卡缓存键也含 bot 与场合，阿莉娜与娜莉灵的记忆不会互相串味。
- **人卡按场合说话（`core/store.py::_person_snapshot_visibility_sql`）**：此前 `person_snapshot` 只看 `subject_id`+`owner_bot_id`，绕过了 `core/visibility.py` 的可见性判定——私聊里说的悄悄话会被塞进群聊的人卡，bot 一张嘴就能抖给全群。现在按 `ctx.scope`/`group_id` 过滤：群聊只给本群的 `group_public` 与 `shareable`，私聊给 `private_pair` / `shareable` / `group_public`，其它场景保守只给 `shareable`；缓存键一并带上场合，人和场合不同就不共用一张卡。
- **不改脱敏**：`core/sensitive_data.py` 只清洗私钥、bearer、密码/API Key、URL 凭据，本来就不碰亲密内容，「保留原文」无需额外开关。
- 新增 `tests/test_memory_tier_and_person_card.py`（11 例）：单字不算刻骨、两个说法才算、强类型+亲密、重要度不再抬档、保护标签仍豁免、群聊人卡不泄漏私聊记忆、未知场合只给 shareable、旧数据补档幂等且不改正文。

### 补齐与清理

- **版本串对齐**：`main.py` 的 `PLUGIN_VERSION` 与旧版/新版页面的静态资源 `?v=` 此前停在 2.3.4，与 metadata/README/CHANGELOG 的 2.3.5 不一致，本版一并拉到 2.3.7。
- **README**：补齐 2.3.3 / 2.3.4 / 2.3.5 / 2.3.7 小节；合并上游 main 的「群聊通知（2026-10-11）/ bot 群 145326153」，内部交流群说明同步更新（本地基线是 tag v2.3.2，比 main 少这一个 docs 提交）。
- **补记两处此前未写入记录的静默清理（行为中性）**：`core/config.py` 删掉重复的 `'maintenance.pending_review_max_age_days'` 映射行；`core/summarizer.py` 删掉重复定义的 `_row_time_evidence`（后一处定义整体覆盖前一处，删除后行为不变）。

## 2.3.5 - 2026-10-17

### 拟人化记忆表达（`memory_humanization.*`，默认关闭）

陪伴场景里，「记得太完美」反而暴露机器感：记忆永远以确定口吻注入、低置信候选整条静默丢弃（模型无从知道自己没把握）、零命中时只有一句中性回退，Bot 于是表现得既不会记不清、也不会想不起来。本切片在**注入措辞层**补上三项人类记忆特征；存储内容、检索正确性、权限与生命周期判定全部不变，`=false` 时注入产物与本版本之前逐字节一致。

- **措辞随时间变淡**：注入器按「记忆年龄 + 置信度」把每条记忆分鲜亮度三档（清晰 / 细节模糊 / 只剩轮廓），非清晰档把该条的「用法」指令降级为只可模糊提及，并标注「记忆印象」。手动固定、关系承诺、伤疤、创作里程碑与高重要度记忆豁免年龄分级——长期承诺不该被时间稀释。`mention_policy` 压制策略与 tone 抽象的优先级高于模糊化。
- **低置信候选改注入「模糊印象」**：声明者为 `uncertain` 的候选不再整条丢弃，改注入独立 `<fuzzy_impressions>` 区块，只给大意并明示不可当事实，使模型自然使用「我记得好像…」「是不是…来着」的求证语气。模糊印象不计入 `included_memory_ids`，不参与注入强化反馈。
- **零召回时诚实提示**：整轮没有任何召回时附带「坦然承认不记得、不要脑补细节」的提示；本轮存在模糊印象时该提示自动让位，避免自相矛盾。
- **接线死代码**：`_hesitation_hint`（Bot 心理能量偏低时的犹豫提示）此前无任何调用点，现接入模糊化条目。
- **运行期取值**：`InjectionComposer` 通过宿主注入的配置提供者读取 `memory_humanization.*`（配置名来自显式白名单表），面板改配置即时生效，无需重建注入器；未挂接提供者时回退到构造参数与内置默认。

### 自然衰减默认值调整

- `maintenance_decay.memory_decay_after_days` 180→90、`memory_decay_idle_days` 90→45：让长期无人提起、且非重要的日常记忆以约一个半月为周期开始变淡，而不是理论上半年后才轮到。代码内回退值不变，仅调整 schema 默认值；保守用法可在面板改回 180/90。

### 兼容性

- 默认关闭，零行为变更；开启后也只影响提示词措辞，不改写任何已存记忆正文。
- 敏感脱敏、画像质量守卫、注入字数预算、查岗轮内容抽象、防提示注入越权等既有红线全部优先于模糊化，并由测试锁死。
- 新增 `tests/test_humanized_injection.py`（22 例，含 4 组红线用例）；全量套件 1184 passed / 2 skipped。

## 2.3.4 - 2026-10-15（本地补丁，非上游；娜莉灵 修改）

### 时间计算跟随 AstrBot 全局时区

- 插件原先在 service / summarizer / bridge / chat_import / qq_history / time_intent /
  page_api / companion_page_legacy 等处一律写死 `Asia/Shanghai`。宿主的 `timezone` 设置
  （`context.get_config().get("timezone")`）与其它插件共用同一个值，写死会让记忆插件在管理员
  改了时区后仍按上海时间解释和展示时间线（时间线本身按 UTC 存储），导致摘要把消息归到错误的
  时段、跨零点时连日期都错。
- 新增 `core/local_time.py` 作为唯一时区来源：启动时绑定宿主时区，取值带 30 秒缓存，非法或
  缺失时回退 `Asia/Shanghai`。所有 `datetime.now(LOCAL_TZ)` / `ZoneInfo("Asia/Shanghai")`
  及提示词里的时区名改为跟随该来源。
- `portrait_service` 的当日批次日期不再回退系统时区。
- 运维诊断新增 `timezone` 字段，便于核对当前生效时区。

### 待修复批次可见、可批量释放、可自动重排

- 面板新增「待修复批次」视图：列出被隔离的总结批次（会话、失败原因、冻结事件数、时间），
  支持逐条与整批「重新排队 / 放弃」；总览的「待修复批次」数字改为可点击进入。
  过去该数字只是计数，释放接口又只能手填批次 ID，隔离区实际无从处理。
- 新增 `list_quarantined_batches` / `release_quarantined_batches` 及两个页面端点
  （`GET /maintenance/summary_batches`、`POST /maintenance/release_summary_batches`）。
- 维护任务按 `memory_summary.quarantine_auto_retry_days`（默认 7 天）自动把闲置的隔离批次
  重新排队，避免隔离区只增不减；`quarantine_auto_retry_limit` 限制每轮数量。

### 修复

- 旧库迁移崩溃：`summary_batches` 在「重建为可空 `next_retry_at`」后会按重建前的列快照再执行一次
  `ALTER TABLE ... ADD COLUMN retry_reason`，对新表而言是重复列，启动即抛
  `duplicate column name: retry_reason`。改为重建后重新读取列信息。
- `summary_progress` 的「待修复批次」不再把旧表 `summary_failures` 行数算进批次数；旧失败记录
  改为独立字段 `legacy_failures`。
- 证据候选有效期：主总结路径原先写死 14 天，改为读取 `memory_summary.candidate_valid_days`，
  与降级候选路径一致。
- 移除死代码：`REPAIR_RETRY_REASON` 常量与恒为假的判断、`MemorySummarizer._row_time_evidence`
  被后定义覆盖的旧实现、`core/config.py` 中重复的 `maintenance.pending_review_max_age_days` 别名。
- `memory_capture.reliable_sources_enabled` 补进配置 schema（此前代码读取但面板无开关）。
- 面板「模块配置」补上 `memory_assertions` / `source_semantic` / `startup` 的中文标签；
  `/config/schema` 回显的 `memory_summary.max_retries` 默认值与运行时统一为 5。

## 2.3.3 - 2026-10-14（本地补丁，非上游；娜莉灵 修改）

### 工具注册改由配置开关控制

- `@filter.llm_tool` 在模块导入时就注册了工具，那时拿不到配置，开关只在函数体内部检查；
  于是关掉的功能仍留在 LLM 的工具列表里，模型先白跑一轮调用（实测 5–10 秒）才拿到
  disabled 错误再重新决策。新增 `_gate_disabled_tools()`，在 `initialize()` 末尾按开关撤下：
  重建类（`sources` / `events` / `navigate` / `discover_sources`，受 `memory_reconstruction.enabled`
  与 `memory_tools.enable_reconstruction_tool`）、`recall`、`remember`、`note_create/read/delete`。
  开关为默认值时行为不变。

### 摘要请求重试次数 0 → 1

- `core/summarizer.py` 调 `provider.text_chat(request_max_retries=0)`；AstrBot 的最小值为 1，
  于是每次总结都记一条 `request_max_retries=0 is below minimum 1` 告警（实测 29 条）。改为 1。

### 开场幕布首帧不闪、去掉逐帧模糊

- `legacy.html` 的幕布底色原本依赖 `app.css` 里的 CSS 变量，样式到达前 WebView 会先画一帧
  未上样式的页面/面板（「一开头闪一下、边角漏出后面的面板」）。在 `<head>` 内联一段首帧兜底
  （页面底色 + 幕布位置/底色），app.css 到达后由它的完整规则接管。
- 标题原本逐帧重算 `filter: blur(12px→0)`，是合成重灾区（手机上掉帧）。改为两层：
  底下 `.intro-ghost` 用**静态**模糊只做淡出，上面 `.intro-title` 清晰淡入；
  「从模糊里显出来」的效果不变，但模糊值从头到尾不重算（help_dex / orbit 同款做法）。

## 2.3.2 - 2026-10-08

### 注入记录可见性修复

- 总览恢复最近注入明细，显示查询、时间、选中记忆、注入字数和过滤数量。
- Memory OS 新版终端增加独立的最近注入状态区和刷新入口，避免新版只显示记忆档案而看不到主链注入状态。
- `/logs` 纳入总览 UI 契约，继续复用后端已有脱敏数据，不新增原文暴露路径。
- 更新静态资源版本标识，避免浏览器继续使用 2.3.1 的页面缓存。

## 2.3.1 - 2026-10-08

### 数据库初始化与关闭竞态修复

- 串行化数据库初始化和服务关闭，避免关闭期间的消息钩子访问已关闭的 SQLite 连接。
- 初始化失败后保留主库连接供重试，并在延迟初始化完成后创建采集运行时。
- 增加初始化失败重试及初始化期间关闭的回归测试。

## 2.3.0 - 2026-10-08

### 原文查询与渐进式 v2 适配

- 接入原文搜索、时间范围、前后文和长消息补读，查询进度记录实际来源片段与有效续页；可选便笺仅保留本轮已读来源的简短理解，不写长期事实。
- 新增默认关闭的 `source-query v2 / range_batch`：按消息观察时间正序批读，实际 UTF-8 JSON 体积、消息数和片段数共同约束输出，长正文使用独立 `srcb_` 游标从真实 offset 连续读取。
- 分别返回遍历、正文展示、事件理解和版本依赖；末行到 EOF 但正文未发完时保留展示缺口，最小片段放不下时明确拒绝，避免漏读与空游标循环。
- 语义片段/相邻窗口维护和后台原文建库支持 dirty 依赖、模型代次、授权复核与暂停恢复；新增来源候选发现及 query-session v3 能力绑定。语义路径默认关闭，需明确配置 embedding Provider、模型修订和维度。
- 保持旧四种原文查询动作和全局版本校验兼容，新能力只有当前原生 handler 与作用域已绑定时提供；关闭查询进度仍保留批读导航预算计量。
- 整合 2.2.3 的断言、异步启动、摘要证据和面板配置改动，统一检查已有静态资源清理及版本标识；CI 补齐真实 AstrBot API 与异步测试依赖。
- 修复 Issue #43 的启发式误判：普通单字不再误触敏感分类或历史开场切分，肯定回应不再被识别为纠正，纯第二人称表达不会保存为用户偏好；历史导入超时默认与配置统一为 300 秒。

### 当前交付边界

- 本版完成 C3 的范围批读基础；共同资源 lease、同轮结果回放、分区 revision 与所有消费者接线仍待后续切片。
- 局部测试证明接口与边界行为，不代表完整 v2 框架、真实语义收益、生产宿主或整周问答质量已经验收。

## 2.2.3 - 2026-10-08

整合 PR #35、#36、#39，并修复 Issues #32、#34、#37、#38、#40、#41、#42。

- 数据库启动和热重载初始化移到工作线程；脱敏与记忆原子回填使用版本标记，维护指纹按批提交，避免重复整表工作压住消息处理。
- 时间证据使用消息时间戳，极性按相关短语判断；引用不存在的消息仍会拒绝，缺乏证据的事实会剔除并保留原因，减少正确总结被隔离的情况。
- 群聊断言归属引用消息的真实发言者，并隔离 Bot 命名空间；待确认候选不会覆盖已接受事实，后续确认可提升候选并连接修订关系。
- 深夜和低能量伤痕闸门接入两条注入路径；动态重建信息放入临时用户上下文，避免逐轮改动系统提示词前缀。
- 混合时区的记忆筛选、排序和分页游标按实际时间比较；情绪目标识别对齐 `self` 归属语义。
- 补齐实际消费的配置项、清理无效控制项，修复带 BOM 的 Provider 配置读取及来源配置合并；尚不存在的协调契约继续如实显示不可用。

## 2.2.2 - 2026-10-05

这一版是「面板与配置的全项体检」，不碰记忆算法。起因是四条反馈：
**联动装了也说不认、皮肤配色配了不生效、开场动画闪一下、面板整体太大。**
其中第一条是 2.2.1 挖出的坑——那一版只修好了一个方向。

---

### 一、联动识别：装与不装都认不出来

**2.2.1 的修法本身有问题。** 那一版用
`importlib.import_module("data.plugins.astrbot_plugin_private_companion.main")`
去找陪伴插件。而 **AstrBot 并不保证插件模块以这个别名留在 `sys.modules` 里**，
所以真装了也 import 不到。于是同一个字段，两个方向的错法：

| 版本 | 判定依据 | 真实含义 | 后果 |
| --- | --- | --- | --- |
| 2.2.1 之前 | `caps.available` | 记忆侧 contract 自检通过（恒 true） | 没装却说装了 |
| 2.2.1 | `importlib.import_module(...)` | —— | **装了也认不出** |

**正确做法是问宿主要当前活着的实例。** 陪伴插件识别记忆插件用的正是这个
（查注册表：`context.get_all_stars()` / `context.get_registered_star()`），
所以直接对齐它的写法：

- 匹配 `metadata` 的 `name` / `display_name` / `root_dir_name` / `module_path`；
- 要求 `metadata.activated` 为真；
- API 优先从模块级 `get_private_companion_api()` 取（那是陪伴插件对外的正式入口，
  它自己就做完了活性检查，判定标准不会在我们这边走样），
  其次从 `star_cls.extension_api` 取，并按对方同样的口径自己校验
  `bridge_lifecycle_status().active is True`。

**最关键的一条设计，必须一起抄**：

> 注册表可用却没找到，就是真的没有，**到此为止**——不再去翻 `sys.modules`。

理由很实在：插件重载后旧模块会留在 `sys.modules` 里冒充还在；
而 `import_module` 更糟——根本没装时它会**凭空造一个空模块**出来，
于是又变回「没装却说装了」。只有宿主压根没有注册表 API（老版本 AstrBot、单测环境）
才退回模块别名，而且只查 `sys.modules.get(...)`，不主动 import。

**另外一个自己踩的坑**：第一版把 context 写成
`getattr(self._plugin, "context", None)`，结果打碎了 `probe_capability_snapshot`
的一条硬约束——**这个探测不许碰 `self._plugin` 任何属性**
（`tests/test_c1_bridge_probe.py` 用一个「摸一下就 AssertionError」的假插件守着）。
改成由调用方传进去：`probe_capability_snapshot(context=None)`。

**还有一处会让人以为没修好**：面板读的是 `__init__` 时拍的那张快照。
用户装完或启用陪伴插件后，要等重启 AstrBot 面板才会变。
改成 `bot_personal_capability_status()` 每次现探，探测失败才退回启动快照。

---

### 二、皮肤配色：14 个选项以前全是空壳

`appearance.theme` 列了 14 个中国传统色，后端 `page_api.THEME_NAME_TO_KEY`
也把色名映射成了 key，但——

> **前端从来没有消费过那个 key，项目里甚至不存在任何一份配色定义。**

所以配置里能选，选了不生效。这不是「回退到默认」，是根本没有这条链路。
接线分三步：

1. `/ui-preferences` 端点返回 `palette` / `theme` / `available_palettes`。
2. `index.html` 在**跳转之前**就调这个端点，拿到 `palette` 先打到 `<html>` 的
   `data-palette` 上。放在跳转前是关键：否则新页面第一帧还是默认色，
   用户会看到一次「颜色跳一下」。
3. `app.css` 新增 14 套 `[data-palette]` 规则，深浅两套共 **28 组**。
4. 面板里改完配色当场调 `syncPalette()`，不用刷新页面——不然用户会以为这项又没生效。

**取色与取值口径**（值得记一笔）：来自《中国传统色：故宫里的色彩美学》的 384 色体系。
两点如实说明——常见的那几个转载站**不是三个独立考据**，是同一套书被抄了三遍；
**墨黪 / 青冥 / 紫蒲** 在深色背景上原本只有 2~4:1，直接当强调色不可用，
已由生成脚本按色相提亮。**28 组配色全部过了 WCAG 4.5:1 的计算校验**，
不是靠眼睛看。

---

### 三、开场动画不再闪

幕布原来是 `0% → 9%` 淡入的。于是面板先完整露一脸，再被幕布盖住，
用户看到的就是「突然闪一下」。改法：

- 幕布**从第一帧就是不透明的**（`0% { opacity: 1 }`），只让里面的字动，幕布本身不动；
- 幕布退场从 90% 收到 68%→92%，缩短「看不见却能点到」的窗口；
- 面板本体在幕布抬起时柔和现身（`body.intro-played` 触发的 `shell-reveal`）。
  **这个 class 只在真的开播时加**——跳过开场的两种情况（减少动效、本会话已播过）
  面板必须立刻可用，不能白等 1.3 秒。

---

### 四、面板整体精简

简洁管理界面整体偏松：22/30px 的内容边距、16px 的卡片间距、236px 的侧栏，
一屏能放的信息太少。这一版整体收紧约 25%——**只动留白与字号，不动配色、不动信息层级**。

**刻意用 `html:not([data-ui-mode="cinema"])` 圈起来。** 放映馆/终端模式有自己那套
空间语言（`app.css` 里 70 处 `data-ui-mode="cinema"` 规则），
压它会毁掉三维终端那套效果，所以这一段对那个模式**完全不生效**——
三维终端按用户要求原样保留。

---

### 五、配置全项体检

按「每一个开关都要有用、他用不用得上」把叶子项逐个核了一遍。
**先纠正一个统计口径：叶子项实际是 201 个，不是之前以为的 188 个。**

判定时的三个陷阱（不避开就会得出「零死开关」的错误结论）：

1. `page_api._schema_config_values()` 遍历 `_conf_schema.json` 本身回显当前值——
   grep 全部 schema 键会在那里 201 项全中。那是**显示**，不是行为控制。
2. `core/config.py` 的 `ConfigView.ALIASES`（48 条旧→新映射）让 34 个 `*_advanced` 键
   在代码里以**旧名**出现。只 grep schema 键会把这 34 项全判成 DEAD。
   而且别名是**单向的、没有反向**——删掉 ALIASES 会让这 34 项同时变 DEAD，
   静态分析完全看不出区别。这是这套配置最大的结构性风险点。
3. `core/operations.py` 的 `PRESETS` 是默认值表，算「被读到」。

| 类别 | 数量 | 处理 |
| --- | --- | --- |
| 确认在生效 | 194 | — |
| 声明了但零引用（假开关） | 4 | 移除 |
| 只有面板在读 | 3 | 1 项修好（配色）、1 项本就是面板开关、1 项假开关已移除 |
| 读出来但没生效 | 0 | — |

**（1）移除 4 个零引用的假开关**（`portrait` 组）：`context_char_limit`、
`context_message_limit`、`token_budget_per_person_day`、`token_budget_global_day`。
四个在 `.py` / `.js` 里一次都没出现过，面板上却各摆着一个滑块。
后两个的 hint 自己写着「**预留**」「**当前不调用画像 LLM**」——功能没做，控件先摆上了。
接线就得凭空发明一套取用规则，所以选择删掉，而不是留一个调了没用的开关。

**（2）移除 1 个描述与实现分裂的开关**：
`private_companion_bridge.preserve_external_prompt_context`。
它只出现在 `page_api` 的配置回显里，控不住任何行为；
而它 hint 描述的那套清理，实际由 `clean_proactive_history` 实现
（`astrbot_compat.sanitize_request_history` 只有这一个门）。
已删除，并把它的说明并进后者，信息没丢。

**（3）6 个默认值与代码 fallback 不一致**（真 bug）：schema 声明的是 2.2.0
**有意调高**的新值，代码里的 fallback 还是旧数。代码 fallback 只在配置项缺失时生效，
所以**从旧版升级上来、老配置里没这个键的用户会吃到另一套参数**——
同一份逻辑两种行为。已把 25 处 fallback 对齐：

| 键 | 旧 fallback | 现 fallback |
| --- | --- | --- |
| `memory_injection.top_k` | 6 | 10 |
| `memory_injection.max_chars` | 1800 | 4000 |
| `memory_injection.max_item_chars` | 220 | 400 |
| `memory_summary.min_events` | 8 | 20 |
| `memory_summary.trigger_event_count` | 12 | 20 |
| `maintenance.retention_raw_event_days` | 7 | 30 |

`core/operations.py` 的三个预设（轻量/标准/陪伴）里仍是旧数字。
**预设是相对档位、刻意不等于默认值**，是有效配置而不是死开关，所以这次没动。

**（4）p5 闸门读错了键名**：`_P5_B_FLAGS` 只写裸名 `enable_p5_b1_recall_gate`，
而 schema 里的真实键是 `private_companion_bridge.enable_p5_b1_recall_gate`，
于是五个闸门永远读到 False，面板的「attestation_read」恒显 `default_off`
——**哪怕用户真把闸门打开了**。已改成全限定名。
另外三个（tool_recall / b2_archive_read / b2_cross_user_read）从来没进过配置，
属于没实现的占位，一并去掉，`total_count` 从 5 变成 2 是如实反映。

**（5）补声明 9 个「代码在读、schema 没写」的键**：它们此前只能手改 `config.json`，
面板里根本看不到。已按代码里的 fallback 补齐声明、类型与默认值：
`retrieval.embedding_index_pending`、`visibility.hide_pending_review`、
`context_orchestration.contextual_query_{expansion_enabled,recent_events,anchor_limit}`、
`maintenance.memory_decay_{scan_limit,include_bot_self}`、
`memory_injection.injection_cache_ttl_seconds`、`memory_injection.hook_request_budget_seconds`。

**（6）修掉一处 JSON 重复键**：`memory_summary.candidate_valid_days` 在 schema 里
出现了两次（逐字相同）。JSON 允许重复键、后者覆盖前者，所以一直没人发现；
而任何按行 diff 的人工审计都会把它当成两项。已合并（合并前逐字比对确认两份完全相同，
所以不改变任何语义）。

---

### 防复发：两条会一直红的守卫

配置体检这种东西只做一次没意义，下次加配置的人照样会忘。所以立了两条检查：

- **`tests/test_config_no_dead_keys.py`**（新增 2 项）：任何 schema 叶子项若在
  全仓库（非测试的 `.py` / `.js` / `.html` / `.css`）找不到字面量引用就报错。
  f-string 拼出来的键由 `DYNAMIC_FAMILIES` 显式展开清单兜底，
  清单里每一条都写了推导依据（在哪一行、展开成哪几个），
  **不靠猜**——这份清单错一条，整条检查就失去意义。
- **`tests/test_config_appearance_wired.py`**（新增 10 项）：凡是 schema 里声明成
  `options` 列表的键，必须同时满足三条：后端有 name→key 映射、
  `app.css` 里有对应的 `[data-palette=...]` 规则、前端会把 key 打到 DOM 上。少一条就红。
  另含 JSON 重复键、缺 `type`、缺 `default`、默认值不在 `options` 里等形状检查。

**两条守卫都验证过「真的会报警」**：往 schema 里注入一个纯装饰的
`visibility.totally_fake_switch`，`test_config_no_dead_keys` 如期报出它；
移除 28 组 CSS 之前，`test_config_appearance_wired` 的三条 CSS 相关用例也是红的。
不验证的守卫可能只是在空转。

---

### 怎么测的

| 手段 | 覆盖什么 | 结果 |
| --- | --- | --- |
| 既有全量测试 | 回归 | 全绿 |
| **探测逻辑逐情形手测**（8 种） | 见下 | 全对 |
| `tests/test_config_no_dead_keys.py`（新增 2 项） | 零引用守卫 + 清单自检 | — |
| `tests/test_config_appearance_wired.py`（新增 10 项） | 配色链路三段 + schema 形状 | — |
| `tests/test_c4_capability_probe.py`（重写，9 项） | 注册表探测的 8 种情形 | — |
| `tests/test_panel_intro_animation.py`（+1 项） | 幕布不透明 + `intro-played` 只在开播时加 | — |
| **配色对比度计算校验** | 28 组 × 深浅，按 WCAG 算相对亮度与比值 | 全部 ≥ 4.5:1 |
| **从解压的 zip 里重跑全量测试** | 发出去的那一份本身自洽 | 760 项通过 |

合计 **760 项通过**（2.2.1 的 749 + 新增守卫），另含 145 项 subtest。

**探测逻辑的 8 种输入**逐条跑过：注册表 `get_all_stars` 命中、
只靠 `get_registered_star` 命中、按 `root_dir_name` 命中、
只有 `get_all_stars` 可用、走模块级正式入口、桥接 `active` 为 false、
插件 `activated` 为 false、注册表里只有记忆插件自己。
外加两条兼容性情形：**陈旧 `sys.modules` 别名不得翻盘**、
无注册表 API 时才允许退回模块别名。

**配色生成器自己也踩了两个坑，都记在脚本里**：
一是把饱和度百分比（18）直接当 0~1 传给 `colorsys`，结果每个 surface 都变成刺眼的原色；
二是「提高对比度」的步进方向搞反了——深色系（墨黪）在深色背景上要**提亮**，
浅色系（黄白游）要**压暗**，固定朝一个方向走会让墨黪一路走到纯黑然后除零。
正确写法是永远朝「远离背景亮度」的方向走。

---

### 边界与如实说明

- `core/p5c_guard.py` 与 `core/p5d_security_events.py` **在仓库里根本不存在**，
  所以协调契约里的 `sink_boundary` / `security_recovery` 两组会一直显示
  `contract_not_available`。面板说的是「拿不到」而不是「正常」，**没有虚标**；
  补齐需要新增两个模块，超出这次范围。
- `core/service.py` 的 `_summary_window_after_failure` 是死代码（定义后无人调用），
  但它影响的配置项在别处仍有活跃读取点，所以没有配置项因此变成空转。
  一并留着没动。
- **一行 diff 噪音需要如实说明**：这一版我用脚本改 `core/service.py`、
  `page_api.py`、`core/coordination_status.py`、`core/bridge.py`、`main.py` 时，
  走了 `pathlib.read_text()` / `write_text()`，而 `read_text()` 会把 `

` 归一成 `
`。
  结果这几个文件的换行符被整体转成了 LF，功能上没有任何影响（Python 两种都认），
  但提交里 `core/service.py` 显示成 `+11684 / -11684` 的整文件重写，
  实际改动只有 25 处 fallback 的数值。**看 diff 时需要留意这一点。**
- 审计报告里列的「11 个未声明键」有 2 个经我核实不成立：
  `startup.background_grace_seconds` 只在开发脚本里出现、
  `livingmemory_migration.default_review_status` 是往 dict 写入而不是从配置读。
  只补了核实过的 9 个。
- 叶子项从 201 变成 205（删 5 增 9）。


## 2.2.1 - 2026-10-05

这一版只动面板与联动状态的**诚实性**，不碰记忆算法。起因是一条反馈：**没装陪伴插件，
面板顶部却显示「已连接」。** 查下来的结论是：问题不在前端取错了字段，而在后端把两个
完全不同的概念塞进了同一个字段。

---

### 一、联动面板把「我方就绪」当成了「对方已安装」

**根因链条**（从后端一路走到前端）：

1. `core/bridge.py` 的 `probe_capability_snapshot()` 调
   `bot_personal_contract.capability_descriptor(available=True, read_only=False)`——
   **`available` 这个参数是写死的**。
2. 它随后只跑 `bot_personal_contract.contract_self_check()`，校验的是
   **记忆侧自己那份** `bot_personal_contract.py` 的自洽性（指纹、窗口覆盖、别名指向）。
   全程**没有任何一行代码检查 `astrbot_plugin_private_companion` 是否加载**。
3. 而在 C4 契约设计里，`available` 的原意是
   **「记忆侧就绪、可以开始和陪伴侧对话」**，它本来就该恒为 true。
4. 前端 `app.js` 的 `companionStatus()` 写的是
   `available: caps.available === true || personal.available === true`
   ——把「我准备好了」读成了「对面装好了」。**这是语义串线，不是显示 bug。**

所以面板从来没骗人，它只是忠实地显示了一个被赋错义的字段。

**为什么没有直接改 `available` 的含义**：`available` 是跨插件契约的一部分，
C1/C4 的启动自检、`test_c6_dual_plugin_boundary` 等一批用例都依赖它。
改语义会波及整条契约链。正确做法是**让「装没装」有独立的取值来源**：

- `core/capability_probe.py` 新增 `detect_companion_plugin()`，并新增两个快照字段
  `companion_installed` / `companion_plugin_name`。
- `build_capability_snapshot()` **保持纯函数**——它不 import 任何插件模块
  （该模块的文档字符串明确写了这条边界），新字段默认 `False`，
  由允许碰运行时的 `bridge` 在调用点填入。
- 判定用陪伴插件的 `get_private_companion_api()` 是否返回非 `None`。
  选它是因为它答的是「**现在真的能用**」，而不是「磁盘上有这个目录」：
  模块能 import 但插件未激活、桥接未就绪时它同样返回 `None`。

**一个必须注意的坑**：新字段必须同时加进 `CAPABILITY_SNAPSHOT_FIELDS`
（= `_SNAPSHOT_KEYS`）。`tests/test_v3_regression_contracts.py` 会扫 `app.js` 里
所有 `caps.<字段>` 引用，逐个核对它是否在 `page_api.ENDPOINT_FIELD_CONTRACT`
声明的范围内。不声明就直接以「面板读取了后端未声明的字段」把测试打红。

**改动清单**：

| 文件 | 改法 |
| --- | --- |
| `core/capability_probe.py` | 新增 `detect_companion_plugin()` + 两个快照字段；`CAPABILITY_STATES`/`_SNAPSHOT_KEYS` 扩容 |
| `core/bridge.py` | `probe_capability_snapshot()` 里探测一次并回填两个字段，`available` 语义一个字未动 |
| `page_api.py` | 新增 `_compatibility_level()`，替掉写死的 `{"compatibility_level": "full"}` |
| `pages/记忆面板/app.js` | 重写 `companionStatus()`；新增 `REASON_TEXT` 对照表与 `healthText`/`bridgeHealthText`/`runtimeHealthText`；概览页与联动页改三态 |
| `pages/记忆面板/app.css` | 新增 `.link-item.is-off` 中性态 |
| `pages/记忆面板/legacy.html` | 新增开场遮罩与收尾脚本 |

---

### 二、「协调契约 · 兼容等级」恒显「契约完全兼容」
