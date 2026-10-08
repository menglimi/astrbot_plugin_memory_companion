# MemoryCompanion 1.9.0 完整升级、优化与重构说明

> 历史版本手册：以下步骤面向 1.9.0，不是当前新框架迁移方案。现有使用说明看[README](./README.md)，新框架设计与当前状态从[设计目录](./docs/README.md)进入。

## 1. 文档信息

| 项目 | 内容 |
|---|---|
| 插件 | `astrbot_plugin_memory_companion`（我会牢牢记住你） |
| Memory 官方 PR 基线 | `main` / Git `d6780bd`（元数据版本 1.7.3） |
| Memory 目标版本 | 1.9.0 |
| Companion 基线 | 6.2.4 / Git `4c93101` |
| Companion 配套版本 | 6.3.0 |
| AstrBot 要求 | `>=4.22.0` |
| 数据库 | SQLite，默认文件 `memory_companion.db` |
| 升级性质 | 存储合同、召回、遗忘、安全、跨插件合同、管理 UI 的全链路重构 |
| 当前状态 | 官方 PR 候选已整理为单提交并完成定向验收；尚未部署或迁移真实生产数据 |
| 文档日期 | 2026-08-16（Asia/Shanghai） |

> 重要：本文是升级交付与操作手册，不代表生产环境已经完成升级。实际部署必须先备份、安排维护窗口，并在目标 AstrBot 实例上完成本文的上线后检查。

## 2. 升级摘要

这次 1.9.0 升级作为一个完整发布单元，包含两个相互配套的工作面：

1. **记忆内核 v2 全链路重构**
   - 引入 Memory Atom v2。
   - 重构身份隔离、证据门控、归类、去重、冲突、召回、强化和自然遗忘。
   - 将 Memory 与 PrivateCompanion 的 Bot Personal 合同升级为 revision 3 / capability 1.3。
   - 增加迁移前自动备份、旧数据脱敏和 scoped namespace 能力。
2. **双 UI 与前后端功能对齐**
   - 保留放映馆界面，新增贯穿总览、工作区和详情页的简洁管理界面。
   - 新增 `memory.page.ui.v2` 前后端能力合同。
   - 将 Memory Atom v2 管理字段接入页面。
   - 补齐跨窗口线程状态和可回滚记忆审计入口。
   - 修复普通编辑会错误复活失效记忆的问题。

升级后的系统不再只是“保存聊天摘要并按分数搜索”，而是形成以下完整链路：

```text
消息捕获
  → 身份、Bot、人格与会话范围解析
  → 时间线与证据保存
  → 事实/偏好/关系/日程/承诺等分类
  → 证据门控与隔离
  → 域内去重、冲突与替代
  → Memory Atom v2 持久化
  → 权限、有效期与所有者硬过滤
  → FTS / Keyword / Embedding / Temporal / Narrow Graph 多路召回
  → RRF 融合 / 可选 Rerank / 类型权重 / 时间衰减 / MMR
  → 分槽与 Token 预算
  → 实际注入回执与轻量强化
  → 后台自然遗忘、压缩与可恢复归档
```

## 3. 本次升级与重构项目

### 3.1 Memory Atom v2 存储合同

新增或正式化以下结构化字段：

| 字段 | 作用 |
|---|---|
| `owner_bot_id` | 明确这条记忆属于哪个 Bot，防止多 Bot 串档 |
| `persona_id` | 绑定人格命名空间，避免同一 Bot 的不同人格互相污染 |
| `validity_status` | 表达 active、superseded、expired、archived、deleted、quarantined |
| `valid_from` / `valid_to` | 表达事实或状态的生效与失效时间 |
| `salience` | 记忆显著性，与旧 `importance` 分离 |
| `durability` | ephemeral、short、normal、durable、pinned 五档耐久度 |
| `sensitivity` | public、internal、private、restricted 四档敏感级别 |
| `reinforcement_score` | 记忆被实际使用后的有限强化值 |
| `injection_count` | 实际进入主模型上下文的次数 |
| `last_injected_at` | 最近一次真实注入时间 |
| `canonical_key` | 绑定平台、Bot、人格、范围和主体的规范化键 |

旧字段继续兼容读取。迁移采用新增列、回填和增量索引，不要求将旧库清空后重新导入。

### 3.2 记忆归类、证据与冲突处理

- 原始聊天先进入时间线，不再直接等同于长期记忆。
- 阶段总结的关键事实和关联必须引用真实时间线事件。
- LLM 输出被视为不可信候选，必须通过本地事件存在性与正文支持检查。
- 证据不足的总结进入 quarantined/pending 隔离区：
  - 不参与正式召回。
  - 不建立向量。
  - 不建立知识图谱。
  - 原始时间线不会被错误标记为已总结。
- canonical key 和内容指纹绑定平台、Bot、人格、scope、session、主体与对象，不会只因文本相同就跨用户、跨群或跨 Bot 合并。
- 新事实可以将旧事实标记为 superseded；失效、隔离和归档状态在评分前被过滤，不会因权重高而“复活”。

### 3.3 召回架构重构

新的召回顺序为：

1. 平台、Bot、人格、scope、session、visibility 和 ACL 硬过滤。
2. lifecycle、validity status 和 valid-time 硬过滤。
3. 本地关键词、FTS、可选 Embedding、时间路由和窄知识图谱分别产生候选。
4. 使用 RRF 按各路线排名融合。
5. 可选 Rerank 二阶段重排；失败自动回退本地路径。
6. 应用类型权重、显著性、时间衰减和有限强化。
7. 使用 MMR 和来源去重抑制同义、同源记忆占满结果。
8. 按自我时间线、用户事实、当前窗口、阶段总结、稳定记忆等分槽分配预算。
9. 只有最终真正进入提示词的记忆才获得注入反馈。

关键变化：**任何权重、Rerank 或 Embedding 都不能绕过身份、权限、有效期和生命周期。**

### 3.4 自然遗忘与权重加成

自然遗忘不再等于定期硬删除，而是四层策略：

1. **检索软衰减**：旧记忆逐渐降低排序权重，但仍可被准确问题召回。
2. **事实失效或替代**：expired / superseded 直接退出正式候选。
3. **归纳压缩和冷归档**：同一作用域内的旧碎片可压缩成高层摘要，原碎片进入可恢复归档。
4. **显式清除**：由管理员或用户明确触发，按确认、备份和范围执行。

默认半衰期：

| 耐久度 | 半衰期 | 典型内容 |
|---|---:|---|
| ephemeral | 1 天 | 临时流水、短暂事件 |
| short | 14 天 | 当前状态、近期日程、短期细节 |
| normal | 120 天 | 普通长期记忆 |
| durable | 730 天 | 偏好、关系、承诺、重要创作 |
| pinned | 不自动衰减 | 明确固定、手工保护记忆 |

真实注入会提供小幅强化，每次增量受限，并随闲置继续衰减。缓存命中、页面检索检查、候选扫描和被 Token 预算裁掉的记录不会获得虚假强化。

### 3.5 信息隔离与 scoped namespace

- 所有读取在排序前和返回前校验平台、Bot、人格、用户/群、会话范围、visibility 与 ACL。
- 缓存键包含身份域和记忆库 revision，撤权后不会继续复用旧授权结果。
- REQ-041 scoped namespace 能力增加：
  - namespace capability 探测。
  - migration epoch / policy version 绑定。
  - scoped record 读、写、列举和 tombstone。
  - 按身份、群或人格的范围清理。
- scoped 操作必须持有 Memory 向当前已加载 Companion 实例签发的 opaque capability。
- 身份上下文、epoch 或 policy 不一致时 fail-closed，不猜测、不部分执行。
- 删除采用 tombstone 保留审计链，避免历史 epoch 回滚后复活已清除数据。

### 3.6 敏感数据与提示注入防护

- 记忆正文、证据、metadata、时间线、历史导入、画像、关系、图谱、scoped payload、失败日志和导出使用统一敏感信息清洗。
- 启动时对旧库执行幂等清洗；受影响记录会重建 canonical/fingerprint/FTS，并清理不再可信的旧向量。
- 凭据、令牌、私钥和敏感 URL 参数不会继续进入正式召回、向量、图谱或导出。
- 记忆与历史聊天内容始终作为不可信资料处理，不能覆盖系统提示词或注入新的系统指令。
- 审计模型只能提出 replace/archive 建议，不能直接修改数据库。

### 3.7 PrivateCompanion 联动升级

推荐与 `astrbot_plugin_private_companion` 6.3.0 同步升级。

升级后的责任边界：

| 组件 | 权威职责 |
|---|---|
| MemoryCompanion | 长期记忆、证据、画像事实、权限、召回、遗忘、注入与审计 |
| PrivateCompanion | 人格、即时情绪、当前状态、日程执行、主动陪伴和最终表达决策 |

联动提升：

- Bot Personal 统一为 revision 3 / capability 1.3 / canonical schema 3。
- DTO 和幂等键纳入 `owner_bot_id + persona_id`。
- outbox 支持幂等、补传、退避、有界保留和失败可见。
- 关系与表达投影使用 sealed producer context。
- 页面健康状态来自正式 capability/coordination 探测，不再把“能读取内部文件”误报为“桥接健康”。
- Companion 缺失、版本不匹配、多 Bot 无法唯一解析或 persona 不匹配时，系统进入明确的 degraded/local-only，不跨域猜测。

### 3.8 双 UI 与前后端能力合同

1.9.0 保留原有放映馆，并新增简洁管理界面：

- 两种界面共用同一个业务 DOM、状态、API、权限和危险操作确认。
- 切换覆盖总览、用户、群聊、个人记忆、知识图谱、记忆显微镜、维护和详情页。
- 简洁模式关闭胶片孔、暗轨、卷轴和转场等待。
- 放映馆继续保留胶片导航、日程卷轴、相册层叠和过场动画。
- 选择保存在浏览器 localStorage，刷新后继续使用。

新增 `memory.page.ui.v2`：

- 后端页面路由：65。
- 前端直接或动态使用：54。
- 前端缺失后端路由：0。
- 其余 11 个接口均标明 internal、compat 或 advanced 及原因。
- 前端启动时核对 contract version、2 种界面、7 类工作区和动态端点。
- 缓存或版本不一致时显示明确警告，不静默展示失效按钮。

### 3.9 管理闭环补齐

- 详情页可查看完整 Memory Atom v2。
- owner Bot、persona、canonical、强化分和实际注入统计只读。
- validity、valid-time、salience、durability、sensitivity 可受控编辑。
- 页面 API 校验枚举、0..1 数值、ISO-8601 格式和有效期先后关系。
- 普通内容编辑不再将 superseded、expired 或 quarantined 静默恢复为 active。
- 跨窗口 thread 支持 close / reopen。
- 维护页支持审计 preview / status / apply / rollback。
- 审计应用和回滚继续要求确认文字，并在执行前备份。

## 4. 升级后的主要提升

| 维度 | 升级前 | 升级后 |
|---|---|---|
| 存储 | importance + metadata 零散字段 | 可索引的 Atom v2、多维生命周期与归属 |
| 归类 | 摘要和原子事实边界不够统一 | 时间线 → 证据候选 → 长期记忆分层 |
| 冲突 | 旧事实缺少明确失效状态 | superseded/expired/quarantined 硬过滤 |
| 去重 | 有跨身份域误合并风险 | canonical/fingerprint 绑定 Bot/persona/scope |
| 召回 | 候选并集合并，重复候选较多 | RRF + 可选 Rerank + 类型权重 + MMR |
| 强化 | 候选阶段就可能增加访问权重 | 只有实际注入后才有限强化 |
| 遗忘 | 偏人工维护，importance 可能形成永久保护 | 耐久度半衰期、软衰减、压缩、冷归档 |
| 证据 | LLM 摘要可能缺少可验证来源 | 事件引用、本地支持校验、失败隔离 |
| 隔离 | 部分链路缺少 Bot/persona 明确字段 | owner/persona/namespace/ACL 全链路校验 |
| Companion | 双端合同漂移可能整体降级 | revision 3 / capability 1.3 严格协商 |
| 管理 UI | 首页切换，详情仍回落放映馆 | 两套完整 UI，工作区和详情全局切换 |
| 前后端对齐 | 靠页面代码隐式假设接口存在 | 版本化 UI capability manifest + 自动测试 |
| 运维 | 迁移、审计和清理入口分散 | 备份、诊断、审计、导入、回滚集中管理 |

固定本地 basic 评测结果：

- 数据：1004 条记录，20 次查询。
- Hit@5：1.0。
- 隐私泄漏：0。
- 主动重建未授权召回：0。
- 热路径 median：0.998 ms。
- p95：358.253 ms，包含冷查询。
- 多跳和时间证据：均命中。

这些数据证明本地默认路径和隔离边界没有退化，但不等于目标服务器上启用 Embedding、Rerank 或外部模型后的真实延迟。

## 5. 升级前准备

### 5.1 必须满足

- AstrBot 版本不低于 4.22.0。
- 确认 Memory 与 Companion 当前版本和插件目录。
- 安排维护窗口，停止外部消息流量。
- 记录现有 Provider、检索、总结、权限拓扑和自然衰减配置。
- 确保数据目录有足够空间保存现有数据库和至少一份完整备份。建议可用空间不低于当前数据库及 WAL 总大小的 2 倍。
- 确认备份目录不会被公网、Web 静态目录或普通用户读取。

### 5.2 需要备份的内容

至少备份：

```text
AstrBot 插件目录/astrbot_plugin_memory_companion/
AstrBot 插件目录/astrbot_plugin_private_companion/     # 使用联动时
AstrBot 插件数据目录/astrbot_plugin_memory_companion/
AstrBot 插件数据目录/astrbot_plugin_private_companion/  # 使用联动时
对应插件配置
```

主要 Memory 数据库：

```text
astrbot_plugin_memory_companion/memory_companion.db
```

不要在插件运行中只复制 `memory_companion.db` 而忽略 WAL/SHM。优先：

1. 停止 AstrBot 后备份整个插件数据目录；或
2. 使用 SQLite backup API / 插件内置导出；或
3. 在确认数据库已安全 checkpoint 后制作一致性副本。

### 5.3 初次上线的安全建议

自然遗忘和自动维护在新默认配置中为开启状态。为了先完成无流量验证，建议：

1. 升级后先不要恢复外部消息流量。
2. 在管理配置中临时设置：

```text
maintenance.auto_schedule_enabled = false
maintenance.memory_decay_enabled = false
```

3. 完成数据库、召回、隔离和 UI 验证。
4. 手动生成维护预览或核对候选后，再恢复默认策略。

审计仍默认关闭：

```text
maintenance_audit.enabled = false
```

它不会随自然维护自动应用模型建议。

## 6. 推荐升级步骤

### 阶段 A：冻结与备份

1. 停止 AstrBot 或至少断开外部消息入口。
2. 保存当前版本、配置和数据数量截图/记录。
3. 备份 Memory、Companion 插件目录和两个插件的数据目录。
4. 校验备份可读、大小合理，记录备份位置。
5. 不删除旧插件目录和旧数据库。

### 阶段 B：同步替换代码

推荐在同一维护窗口同时升级：

- MemoryCompanion 1.9.0。
- PrivateCompanion 6.3.0。

插件目录名保持：

```text
astrbot_plugin_memory_companion
astrbot_plugin_private_companion
```

不要把新版文件直接散落覆盖在未知状态的旧目录上。安全做法是：

1. 将新版解压到临时目录。
2. 核对 `metadata.yaml` 和目录结构。
3. 将旧目录重命名为带时间戳的代码备份。
4. 将完整新版目录移动到正式插件路径。
5. 保留插件数据目录，不用空目录覆盖数据目录。

### 阶段 C：首次启动和自动迁移

首次启动时 Memory 会：

1. 开启 SQLite WAL 与外键。
2. 检测现有 schema。
3. 在修改旧 schema 或清洗旧数据前，通过 SQLite backup API 生成一致性备份。
4. 将备份权限设置为 `0600`（Linux/Unix）。
5. 新增 Atom v2 列和索引并回填兼容值。
6. 建立 namespace scoped 表和索引。
7. 幂等清洗旧敏感数据。
8. 写入 `schema_metadata=memory-atom-v2`。

自动备份文件形式：

```text
memory_companion.before-memory-atom-v2.<UTC时间戳>.db
```

注意：

- 新建空数据库不会生成无意义升级备份。
- 同一个已经成功升级的数据库重复启动不会反复生成 schema 备份。
- 如果升级前数据库含有历史凭据，迁移前备份也可能含原始敏感值；必须将其作为高敏文件保护。

### 阶段 D：无流量验证

启动后先检查日志：

- Memory 版本为 1.9.0。
- Companion 版本为 6.3.0。
- 没有 schema migration、database locked、malformed database 等错误。
- Memory 日志打印正确数据目录。
- Companion capability/coordination 没有 contract fingerprint mismatch。
- 如果检测到旧版本或缺插件，状态应为 degraded/local-only，而不是跨域继续写入。

然后执行第 8 节的验收清单。

### 阶段 E：逐步恢复流量

1. 先恢复一个测试 Bot 或少量测试会话。
2. 验证私聊、群聊和个人记忆隔离。
3. 检查一次真实注入日志，确认 selected 和 actual injection 一致。
4. 验证 Companion 日程/相册/当前状态不会被 Memory 重复注入。
5. 观察一个维护周期后再恢复自然衰减自动调度。
6. 保留迁移前备份至少一个可接受的回滚观察期。

## 7. 升级后配置建议

### 7.1 推荐保持

```text
memory_capture.enabled = true
memory_summary.enabled = true
memory_injection.enabled = true
retrieval.mode = auto
context_orchestration.query_mode = current_message
private_companion_bridge.dedupe_prompt_context = true
private_companion_bridge.prefer_memory_companion_memory = true
```

### 7.2 默认关闭或谨慎开启

| 配置 | 默认 | 建议 |
|---|---:|---|
| `retrieval.embedding_enabled` | false | 需要语义补召回且明确数据出境边界后再开 |
| `private_companion_bridge.cross_window_emotional_continuity_enabled` | false | 只有明确需要跨窗口情绪延续时开启 |
| `maintenance_audit.enabled` | false | 仅管理员手动审计时临时开启 |
| `memory_injection.debug_log_injection_enabled` | false | 排障时短期开启，结束后关闭 |
| `maintenance.sleep_backup_enabled` | false | 需要每次维护备份时开启，注意磁盘增长 |

### 7.3 兼容配置

```text
private_companion_bridge.legacy_emotion_compatibility_enabled = true
```

该开关只用于旧版 Companion 的同一精确私聊窗口兼容。Memory 和 Companion 都升级完成并验证新版能力上下文后，建议关闭，缩小兼容攻击面。

### 7.4 自然遗忘推荐策略

正式启用前检查：

```text
maintenance.memory_decay_enabled = true
maintenance.auto_schedule_enabled = true
maintenance.auto_startup_delay_seconds = 120
maintenance.auto_interval_hours = 24
maintenance.memory_decay_archive_without_summary = true
```

高级默认阈值：

- 记忆存在 180 天后才可能成为衰减候选。
- 距离上次召回 90 天后才可能衰减。
- 单次最多检查 120 条候选。
- 单次最多处理 8 个窗口组。
- 同一窗口至少 4 条碎片才尝试压缩摘要。

自然衰减按窗口分组，不会将不同私聊、群聊或人格的碎片合并。

## 8. 升级后验收清单

### 8.1 数据与迁移

- [ ] 升级前数据库备份存在，权限与位置安全。
- [ ] `memory_companion.db` 可打开，无损坏错误。
- [ ] 升级前后总记忆数、私聊数、群聊数变化可解释。
- [ ] 随机检查旧记忆正文、证据、scope、session、用户和群归属。
- [ ] 检查 Atom 字段已生成，旧数据没有被跨 Bot/persona 误归属。
- [ ] 多 Bot 环境检查 owner 为空的 legacy 记录；系统不会凭猜测自动绑定所有者。
- [ ] Embedding 开启时检查补向量任务和 Provider 可用性。

### 8.2 召回与隔离

- [ ] 私聊用户 A 无法召回用户 B 的私聊。
- [ ] 群成员无法自然读取未授权私聊记忆。
- [ ] 群聊 A 无法读取群聊 B 的内部记忆。
- [ ] Bot A 无法读取 Bot B 的 owner-bound 记忆。
- [ ] Persona A 无法读取 Persona B 的人格记忆。
- [ ] 撤销 ACL 后刷新和缓存命中结果均不再返回该记忆。
- [ ] expired、superseded、archived、quarantined 不进入正式召回。
- [ ] 当前状态问题不会被很久以前的日程或状态回答。

### 8.3 Companion 联动

- [ ] 页面显示正式 bridge/coordination 状态为健康。
- [ ] Bot Personal 的 owner Bot 和 persona 匹配。
- [ ] Companion 日程、相册和主观记忆可读取。
- [ ] 错 persona 读取返回空或拒绝，不回退到其它人格。
- [ ] outbox 失败时可观察，恢复后可以幂等补传。
- [ ] 当前状态只由 Companion 提供一次，Memory 不重复注入同段内容。

### 8.4 管理 UI

- [ ] “简洁管理 / 放映馆界面”在总览和任意详情页都可切换。
- [ ] 切换后当前工作区、用户/群、筛选和打开详情不丢失。
- [ ] 刷新后保持界面选择。
- [ ] 页面不显示 `memory.page.ui.v2` 不兼容警告。
- [ ] 用户、群聊、个人、图谱、显微镜和维护六个工作区可打开。
- [ ] 详情页可查看 Atom 字段；系统归属和强化字段不可编辑。
- [ ] 修改 validity/time/salience/durability/sensitivity 后重新读取一致。
- [ ] thread close/reopen 可用。
- [ ] audit preview/status 可用；apply/rollback 仍要求确认。

### 8.5 维护与回滚准备

- [ ] 手工维护能输出诊断，不出现跨窗口混合。
- [ ] 可移植 JSONL 可以导出并通过预览。
- [ ] 不在生产库上直接测试清空、导入或审计 apply。
- [ ] 已记录迁移前备份、当前库、代码备份和回滚负责人。
- [ ] 完成一个实际观察周期后再清理旧代码和迁移备份。

## 9. 安全性提升

### 9.1 已落地的安全控制

| 控制 | 防护目标 |
|---|---|
| owner Bot + persona + scope + ACL 前置过滤 | 防止跨 Bot、跨人格、跨用户和跨群泄漏 |
| valid-time / validity / lifecycle 前置过滤 | 防止旧事实、失效事实或隔离候选重新进入回答 |
| namespace opaque capability | 防止未授权插件调用 scoped 读写和清理 |
| epoch / policy version 绑定 | 防止旧协议回放和迁移状态混用 |
| tombstone 清理 | 防止历史 epoch 回滚复活已删除数据 |
| 敏感数据统一清洗 | 防止凭据进入记忆、向量、图谱、日志和导出 |
| LLM 证据门控 | 防止无来源总结直接成为长期事实 |
| 不可信资料提示边界 | 降低聊天内容或旧记忆中的提示注入风险 |
| 实际注入反馈 | 防止候选扫描形成自我强化偏置 |
| 审计预览 + 指纹 + 确认 + 备份 | 防止模型建议自动修改数据库 |
| Schema 迁移前一致性备份 | 提供数据级回滚点 |
| UI/API 版本合同 | 防止缓存旧前端时静默调用错误接口 |

### 9.2 管理和部署侧仍需负责

- 不要将 AstrBot 管理页面直接暴露到公网。
- 管理账号、反向代理、Cookie、TLS 和访问控制仍由 AstrBot/部署环境负责。
- 数据库、备份、可移植导出和历史聊天原文都包含个人数据，应纳入备份加密和最小权限策略。
- 开启外部模型前必须确认数据处理协议和数据驻留要求。
- 调试日志只在必要时开启，完成排障后及时关闭并按保留期清理。

## 10. 可能风险与缓解措施

| 风险 | 级别 | 可能表现 | 缓解措施 | 回滚触发条件 |
|---|---|---|---|---|
| 首次 schema 迁移失败 | 高 | 启动失败、列或索引不完整 | 停流量；保留自动备份；检查磁盘、权限和 SQLite 完整性 | 数据库损坏、重复迁移仍失败 |
| 自动自然遗忘提前运行 | 高 | 旧碎片被压缩或归档 | 首次无流量验证时临时关闭 auto schedule 与 decay；先手工检查 | 大量非预期 archived 或摘要 |
| 迁移前备份含旧敏感值 | 高 | 备份保留升级前的令牌/凭据 | `0600`、受限目录、加密备份、设定删除周期 | 备份泄露或权限错误 |
| 外部 Embedding/Rerank/总结模型看到记忆文本 | 高 | 私聊内容离开本机 | 保持 Embedding 默认关闭；使用可信/本地 Provider；限制用途 | 发现未授权外发或 Provider 配置错误 |
| Companion 版本未同步 | 中 | Bot Personal、关系或表达联动 degraded | 同维护窗口升级到 6.3.0；检查 capability fingerprint | 长期 degraded、outbox 持续失败 |
| 多 Bot / 多 persona 旧数据缺少明确 owner | 中 | 部分记忆降级、无法严格归属 | 人工核对 legacy 记录；不要批量猜测绑定 | 出现跨 Bot 候选或大量不可用记忆 |
| 新召回排序改变回答偏好 | 中 | 更重视新事实、多样性提高，旧高分记忆减少 | 使用记忆显微镜对固定问题回归；调 retrieval/slot 预算 | 关键事实召回率明显下降 |
| Restricted 记忆不再召回 | 中 | 管理可见但对话不使用 | 核对 sensitivity；只对确需召回的记录改为 private/internal | 业务必需记忆被错误标为 restricted |
| 首次清洗导致旧向量失效 | 中 | Embedding 命中暂时减少 | 允许后台 backfill；检查 Provider；保留 FTS/basic 回退 | 向量长期无法重建且语义召回明显下降 |
| 页面缓存前后端版本不一致 | 低 | 显示 capability 警告或按钮不可用 | 清理插件静态缓存、硬刷新、核对 1.9.0 资源版本 | 刷新后仍 contract mismatch |
| 维护备份和 WAL 占用磁盘 | 中 | 磁盘增长、写入失败 | 监控 DB/WAL/备份；设置保留周期；不要盲目开启每次维护备份 | 磁盘剩余空间进入告警阈值 |
| 范围 ACL 配置错误 | 高 | 私聊记忆被允许到错误群 | 使用权限拓扑逐条授权；做当前发言者负例测试 | 任意未授权召回或跨用户泄漏 |
| 审计建议误修正 | 中 | 内容被 replace 或 archive | 保持默认关闭；只预览；检查证据；应用前备份；支持 rollback | 应用后出现事实错误或误归档 |
| 当前容器全量异步测试阻塞 | 低（工程） | 无法得到一次全量 runner 绿灯 | 依赖已通过定向测试；在目标 CI/运行环境复跑 | 目标环境也出现运行时线程阻塞 |

## 11. 回滚方案

### 11.1 只回滚 UI 1.9.0

如果数据库、召回和 Companion 都正常，只是新 UI 有问题：

1. 停止插件或 AstrBot。
2. 恢复 1.8.0 的 `pages/记忆面板`、`page_api.py`、Atom 页面序列化/更新相关代码。
3. 保留已经升级的 Atom v2 数据库。
4. 重新启动并清理浏览器/插件静态缓存。

UI 回滚通常不需要恢复数据库，但普通编辑状态一致性修复也位于 1.9.0；回退前应确认不会重新引入“编辑即复活”的旧行为。

### 11.2 完整代码回滚

完整回滚点：

```text
Memory:    67d8c1d（1.7.3 基线）
Companion: 4c93101（6.2.4 基线）
```

步骤：

1. 停止 AstrBot，禁止新写入。
2. 保存当前 1.9.0 数据库、WAL、SHM、日志和代码，不直接删除。
3. 恢复旧 Memory 与旧 Companion 代码目录。
4. 按 11.3 恢复迁移前数据库。
5. 恢复升级前配置。
6. 启动后验证旧版本数据数量和基础私聊/群聊召回。

### 11.3 数据库回滚

使用首次迁移前生成的：

```text
memory_companion.before-memory-atom-v2.<UTC时间戳>.db
```

安全步骤：

1. 停止 AstrBot。
2. 将当前 `memory_companion.db`、`memory_companion.db-wal`、`memory_companion.db-shm` 移到隔离备份目录。
3. 复制迁移前备份为 `memory_companion.db`。
4. 在 Linux/Unix 上将权限设为仅服务账户可读写，例如 `0600`。
5. 同时恢复兼容的旧代码；否则 1.9.0 会再次迁移该旧数据库。
6. 启动并执行完整性、数量、归属和召回检查。

不要在进程运行时覆盖数据库，不要只删除 WAL/SHM 后继续运行，也不要使用不明来源的 SQLite 文件。

### 11.4 审计批次回滚

已应用的记忆审计可使用：

```text
/mcomp audit rollback <batch_id> 确认
```

系统会：

- 再次备份当前数据库。
- 校验当前指纹，避免覆盖审计后的人工作业。
- 恢复内容、证据、权重、lifecycle 和 Atom 可写状态。
- 将发生后续人工修改的记录标记为 stale 并跳过。

### 11.5 历史聊天导入回滚

历史导入批次支持整批回滚，仅删除该批时间线、记忆、向量、图谱边和关系候选，不影响其它批次。不可变原文会保留，便于审计和重新整理。

## 12. 已知限制与后续观察项

1. 当前改动尚未在真实 AstrBot 生产实例中执行升级和长时间运行观察。
2. 当前本地 benchmark 使用 basic 模式，不代表外部 Embedding、Rerank 和总结模型延迟。
3. 旧 benchmark 包名曾失效，因此没有严格同机旧数值 A/B；已有固定金标、时间、纠错、多跳和零泄漏回归作为不退化证据。
4. 当前容器的部分旧异步用例在首个 `asyncio.to_thread` 调用处阻塞；最终集成分支改用 72 项不重叠的关键定向测试验收。阻塞属于运行环境限制，仍需在真实 AstrBot/CI 环境补跑完整套件。
5. 未启动 AstrBot WebView 宿主，因此双 UI 的像素、焦点顺序和真实触摸手势仍需部署后人工验收。
6. Memory 的 clear all 只能清理自身数据库、投影和 scoped 状态，不能单向物理删除 Companion 源 JSON/即时状态；跨插件原子删除仍需要独立 saga 设计。
7. 可移植 JSONL 不包含 Provider 凭据、向量索引和注入日志；恢复后向量需要在目标 Provider 下重建。

## 13. 验证证据摘要

### 内核与联动

- C1 契约、Memory Atom v2、REQ-041 namespace/capability/scoped bridge：37/37。
- Bot Personal C3 agenda 语义：5/5。
- Memory 侧 revision 3 命名空间边界、同 persona 可读与错 persona 拒绝：通过。
- Memory 合同指纹 `ecf1d69406a8445d`，自检通过；生产联动仍须确认 Companion 6.3.0 报告相同指纹。
- 本地 basic benchmark：Hit@5=1.0、privacy leaks=0、unauthorized active reconstruction=0。

### UI 与管理合同

- 双 UI、UI/API、Atom handler、真实注入反馈、自然遗忘与多路融合：30/30。
- JavaScript syntax：通过。
- Python compileall：通过。
- JSON schema：通过。
- `git diff --check`：通过。

### 验收状态

```text
passed_with_environment_note
```

环境说明不会降低已通过定向链路的结果，但生产上线仍必须执行本文第 8 节。

## 14. 相关文件

- [README.md](README.md)
- [CHANGELOG.md](CHANGELOG.md)
- [metadata.yaml](metadata.yaml)
- [配置 Schema](_conf_schema.json)
- [Memory Atom 实现](core/memory_atom.py)
- [自然遗忘策略](core/memory_lifecycle.py)
- [存储与迁移](core/store.py)
- [召回实现](core/retrieval.py)
- [注入实现](core/injection.py)
- [Companion Bridge](core/bridge.py)
- [页面 API](page_api.py)
- [管理页面](pages/记忆面板/index.html)

## 15. 上线批准建议

建议只有同时满足以下条件才进入生产流量：

- 已获得明确部署授权。
- 代码与数据备份已验证。
- Memory 1.9.0 与 Companion 6.3.0 已同步放置。
- 首次迁移成功并确认自动回滚副本存在。
- 私聊、群聊、Bot、persona 和 ACL 负例无泄漏。
- 两种 UI 和 `memory.page.ui.v2` 合同无告警。
- 自然遗忘先在无流量或低流量阶段验证。
- 外部 Provider 的数据处理边界已确认。
- 回滚负责人、备份位置和回滚窗口已记录。

在上述条件完成前，应保持“PR 待审、本地验收完成、生产未升级”的状态。
