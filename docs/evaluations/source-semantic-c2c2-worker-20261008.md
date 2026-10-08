# C2c-2 原文语义后台构建 · 2026-10-08

本文记录 C2c-1 确定性来源维护基础之上的后台建库切片。它证明本地 worker、generation 生命周期和迟到结果围栏的代码行为，不证明真实 Provider、语义相关性或完整生产吞吐。来源发现 owner 与 query-session v3 已在后续切片接入，相关契约和回归见 `tests/test_source_discovery.py`、`tests/test_query_session.py` 及 `docs/contracts/query-session/v3/`。

## 本轮交付

- 新增独立 `source_semantic` 配置，默认关闭。启用时必须明确指定 embedding Provider ID、模型修订和向量维度；不会自动挑选 Provider，也不会沿用长期记忆 embedding 的回填开关。
- generation 绑定当前 `SessionContext` 的来源分区、Provider/模型/维度、编码、脱敏处理修订、片段/窗口 profile 与历史回填模式。来源仍由原 timeline owner 持有；索引只存 hash、span、依赖、revision 和向量。
- 默认只处理触发建库的来源，coverage 配置为 `incremental_only`。历史回填须单独启用，按稳定 ID 分页；每次唤醒最多处理 1-32 个来源和 1-32 次 Provider 调用，默认分别为 4 和 8。
- 历史扫描把本页候选与 checkpoint 放在同一事务内写入 semantic dirty 队列。暂停或关闭时，尚未嵌入的来源仍有持久待办；provider 错误保留 pending 文档和 dirty，之后可显式续跑。
- 每个来源按脱敏可读投影构造片段，并在可信时间和合法邻居可用时构造窗口。Provider 请求前先短事务登记 pending；网络调用期间不持有 SQLite 写事务。返回必须恰好对应一个有限、非零且维度匹配的向量，提交时重验来源修订、权限、generation 配置和窗口邻接。
- generation 支持暂停、恢复和退休。取消后不会发布结果；generation 退休、来源修订变化或配置变化时，迟到结果不能覆盖索引。Provider 调用写入独立的 `source_semantic_embedding` 用量类别，并与现有后台 embedding 并发 semaphore 共用并发槽。

## 定向验证

使用 AstrBot 自带 Python：

```powershell
C:\Users\99505\.astrbot\backend\python\python.exe -X utf8 -m pytest -q tests\test_source_semantic.py tests\test_source_semantic_worker.py tests\test_config_schema_coverage.py
C:\Users\99505\.astrbot\backend\python\python.exe -X utf8 -m py_compile core\source_semantic.py core\service.py tests\test_source_semantic.py tests\test_source_semantic_worker.py
```

结果：**18 passed，8 subtests passed**；`py_compile` 成功。worker 测试使用 Provider 替身，覆盖当前来源入库、历史扫描续跑、单输入多向量拒绝、活跃批次期间新来源的续调度、暂停取消/恢复、generation 退休迟到结果和来源修订变化。没有调用真实模型或 AstrBot 宿主 Provider。

## 当前仍未覆盖

- 前台查询优先级、跨前后台的 Provider 请求/Token 总预算、真实宿主 Provider 的编码模式与用量验证。
- C2b 整包验收、陌生问法正确率、吞吐/锁等待/WAL/RSS 与完整宿主关闭重启验收。

历史回填默认关闭。关闭时 generation 的 `ready` 只说明增量配置下当前待办已处理，不代表该会话历史完整；查询消费者按 `coverage_mode=incremental_only` 报告 `partial`，不能把没有命中解释成没有记录。启用历史回填且扫描、dirty、顺序变更、pending/stale 文档均清零时，来源发现会报告 `index_coverage=complete`。本记录仍不替代真实 Provider 和生产宿主验收。
