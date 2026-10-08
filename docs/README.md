# 记忆领域设计目录

> 整理：2026-09-16。这里是 Memory 新框架设计的本地唯一入口。八插件整体设计从[统一入口](../../astrbot_plugin_private_companion/docs/README.md)进入；全局阶段、最新进度和下一项开发只以[路线看板](../../astrbot_plugin_private_companion/docs/FRAMEWORK_ROADMAP_AND_STATUS_V1.md)及其状态数据为准。

Memory 负责长期事实、获授权的证据、检索、纠正、生命周期与保留。来源领域继续拥有原始消息和业务事实，Role/Runtime 负责当前回复与行动决策，Memory 不建立第二套世界、日历、作品或投递状态。仓库目录是 `astrbot_plugin_remember_you`，插件 ID 是 `astrbot_plugin_memory_companion`；目录名不能充当授权身份或稳定 owner。

## 插件代码与日常维护

本索引主要维护记忆领域设计、跨插件契约和阶段证据。若要了解 AstrBot 加载入口、当前源码目录、模块职责或测试命令，请从[插件结构与维护入口](./PLUGIN_STRUCTURE.md)开始；用户功能和配置说明见[插件 README](../README.md)。

## 1. 三条阅读路径

| 目的 | 推荐顺序 |
| --- | --- |
| 理解整体设计 | [记忆总体设计](../../astrbot_plugin_private_companion/docs/MEMORY_CONTRACT_V0.md) → [提议与查询接口](../../astrbot_plugin_private_companion/docs/MEMORY_PROPOSAL_QUERY_CONTRACT_V0.md) → [写入与恢复状态机](../../astrbot_plugin_private_companion/docs/MEMORY_VERTICAL_SLICE_STATE_MACHINE_V0.md) |
| 开发当前切片 | [复杂查询 A/B/C](../../astrbot_plugin_private_companion/docs/MEMORY_QUERY_SESSION_DESIGN_V0.md) → [本地参考适配器](./MEMORY_ADAPTER_DESIGN_V0.md) → 下方本地契约包 |
| 验证能否进入下一阶段 | [反例与验收](../../astrbot_plugin_private_companion/docs/MEMORY_COUNTEREXAMPLE_EVAL_V0.md) → [原文保存与恢复](../../astrbot_plugin_private_companion/docs/MEMORY_SOURCE_CAPTURE_RECOVERY_V0.md) → [S3 联合验收](../../astrbot_plugin_private_companion/docs/S3_INTEGRATED_ACCEPTANCE_V0.md) → [验证记录](../../astrbot_plugin_private_companion/docs/evaluations/README.md) |

## 2. 责任稿与冲突裁决

| 问题 | 权威稿 | 本仓库承担什么 |
| --- | --- | --- |
| Memory 有哪些对象、怎样写入和召回 | [记忆总体设计](../../astrbot_plugin_private_companion/docs/MEMORY_CONTRACT_V0.md) | 不复制公共语义，只映射现有存储和检索 |
| 外部插件怎样调用、返回什么字段 | [提议与查询接口](../../astrbot_plugin_private_companion/docs/MEMORY_PROPOSAL_QUERY_CONTRACT_V0.md) | 提供兼容 adapter 和本地 profile |
| revision、纠正、撤回、outbox 怎样流转 | [写入与恢复状态机](../../astrbot_plugin_private_companion/docs/MEMORY_VERTICAL_SLICE_STATE_MACHINE_V0.md) | 在 owner 事务内实现并留下可查回执 |
| 大资料和复杂问题怎样推进 | [复杂查询 A/B/C](../../astrbot_plugin_private_companion/docs/MEMORY_QUERY_SESSION_DESIGN_V0.md) | 实现 source/event/query-session/vector 等本地能力 |
| 原文漏捕、补偿和恢复怎样处理 | [原文保存与恢复](../../astrbot_plugin_private_companion/docs/MEMORY_SOURCE_CAPTURE_RECOVERY_V0.md) | 保存来源、任务与消费侧需要的真实状态 |
| 怎样判定 S3 收口 | [S3 联合验收](../../astrbot_plugin_private_companion/docs/S3_INTEGRATED_ACCEPTANCE_V0.md) | 提供真实 owner、非空数据、回执和完整重启证据 |
| 当前代码对应设计中的哪一部分 | [本地参考适配器](./MEMORY_ADAPTER_DESIGN_V0.md) | 这是实现映射稿，不覆盖上述公共决定 |
| 现在做到哪、下一步是什么 | [路线看板](../../astrbot_plugin_private_companion/docs/FRAMEWORK_ROADMAP_AND_STATUS_V1.md) | 不在各专题重复维护全局进度 |

若文档冲突，字段与能力封套回接口稿，状态转移回状态机，查询路线回 A/B/C 专题，阶段与证据回路线看板。日期化报告只证明当时实际覆盖的范围，不能反向修改权威设计。

## 3. 本仓库的设计材料

| 材料 | 定位 | 是否现行规范 |
| --- | --- | --- |
| [本地参考适配器](./MEMORY_ADAPTER_DESIGN_V0.md) | 现有入口、代码、事务和标准能力之间的映射 | 是本地实施主稿；公共语义仍以上表主稿为准 |
| [2026-09-06 精度审查](./MEMORY_PRECISION_REVIEW_20260906.md) | 六类已复现问题、评测口径与设计来源 | 历史审查，不代表问题仍未修或已经验收 |
| [2026-09-07 提议通道升级](./MEMORY_PROPOSAL_UPGRADE_20260907.md) | 旧 `MemoryProposal` 通道的演进记录 | 历史实现来源，不替代现行公共接口 |
| `docs/evaluations/*.json` | 模型、性能和路线对照的原始数据 | 由公共验证报告解释，不能单独宣称通过 |

现有插件功能和配置看[插件 README](../README.md)，版本变化看[CHANGELOG](../CHANGELOG.md)，旧版本升级看[1.9.0 升级说明](../UPGRADE-1.9.0-完整升级说明.md)。

## 4. 本地机器契约

这些包描述当前 Memory 宿主内的局部格式，与公共 Memory 契约分层维护；本地 profile 可先实现，不等于公共 SDK 已冻结。

| 包 | 作用 | 当前边界 |
| --- | --- | --- |
| [source-query v1](./contracts/source-query/v1/README.md) | 原文搜索、范围翻页、前后文和长消息补读 | 已有局部 C/R/H；完整来源捕获与恢复另按 CAP 验收 |
| [source-query v2](./contracts/source-query/v2/README.md) | C3 范围正序批读、UTF-8 预算和长消息连续偏移 | 默认关闭；沿用原导航预算和 global validity，未实现 lease/回放/scoped |
| [event-query v1](./contracts/event-query/v1/README.md) | 对已读来源做临时事件排序、计数和分组 | 程序核验来源，模型语义正确性单独验收 |
| [query-session v1](./contracts/query-session/v1/README.md) | A：记录同轮实际查询进度 | 已本地实现，模块已加载；实际请求与生产效果另验 |
| [query-session v2](./contracts/query-session/v2/README.md) | B：可选便笺、来源关联和回看 | 已本地实现，自主使用和收益尚未证明 |
| [query-session v3](./contracts/query-session/v3/README.md) | discover 与 range_batch 的本轮能力接线 | 局部实现；真实 Provider/宿主与共同资源账本另验 |

## 5. 当前状态快照

截至 2026-10-08，整体仍为 **S2→S3**。本地已保存完整脱敏来源/chunks 和事务回执，接入持久交接、本机 friend_recall 与完整 timeline 兼容投影；覆盖为已观察入口，完整 CAP 库存/可信恢复和公共消费绑定尚未完成。A/B/C2a 模块已随宿主恢复加载，实际请求工具与生产收益仍须采样。最新证据见[连续生活贯通报告](../../astrbot_plugin_private_companion/docs/evaluations/S4_LIFE_COMPLETE_20260916.md)。本轮已补 C2b context 时间定位、C2c 依赖/dirty 基础、有界可暂停恢复的后台原文语义建库、授权来源发现/融合/原文回读和 query-session v3 绑定；语义路径默认关闭，真实 Provider 与生产收益未验收。C3 已交付默认关闭的范围批读、UTF-8 owner 预算与真实正文 continuation，仍使用旧导航步骤和 global validity。

后续依次验证 C2c 真实语义收益，继续 C3 的共同资源、精确回放与分区失效，再推进 C4 同预算真实模型验收。C2b 尚未通过整包验收：长词 trigram 可用；双字和混合短长词仍走授权分区字面扫描；context 索引条件已有局部回归。C2c 前两阶段记录见[维护基础](./evaluations/source-semantic-c2c1-maintenance-20261008.md)和[后台构建](./evaluations/source-semantic-c2c2-worker-20261008.md)，后续局部查询测试不等于真实 embedding 质量证据。SAC-01--20 与 CAP-01--24 仍全部 `not_run`；正式 MRQ 运行仍为 0，独立结构、标准订阅、生产日期问答与完整重启恢复仍待证明。任何全局状态更新均回写路线看板和状态数据，本页只保留便于定位的快照。

## 6. 维护规则

1. 新的公共字段、状态或阶段决定写入对应权威稿，不在本仓库另造同义协议。
2. 现有代码接点、兼容限制和本地事务方案写入适配器稿；局部 wire 格式写入对应契约包。
3. 实际测试、模型、宿主加载和生产结果写入日期化报告，原始 JSON 留在 `docs/evaluations/`。
4. 测试数量、Schema 数量、设计确认和真实运行分开记录，不合并成完成百分比。
5. 新想法先进入[三句话登记页](../../astrbot_plugin_private_companion/docs/IDEA_BACKLOG.md#quick-idea)，明确 owner 后再并入责任稿。
