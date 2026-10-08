# 插件结构与维护入口

本文对应当前插件目录，说明运行入口、模块边界和本地验证方式。它是代码导航，不替代 [记忆领域设计目录](./README.md) 中的接口契约和设计决定。

## 运行入口

| 路径 | 职责 | 维护约束 |
| --- | --- | --- |
| `__init__.py` | 暴露 AstrBot 插件类，兼容包导入 | 保留导出名 `MemoryCompanionPlugin` |
| `main.py` | AstrBot `Star` 插件入口、事件钩子、工具和命令注册 | 保留 AstrBot 扫描入口及桥接 getter |
| `metadata.yaml`、`logo.png` | 插件市场元数据与图标 | 文件名由 AstrBot 插件包约定使用 |
| `_conf_schema.json` | 管理页读取的配置 Schema | `page_api.py` 按同目录路径读取，不能单独移动 |
| `page_api.py` | Quart 管理页 API、静态页面路由和后端投影 | 对外路径属于前端契约；拆分时先保留 `PluginPageApi` 导入面 |
| `companion_page_bridge.py`、`companion_page_legacy.py` | 读取陪伴插件页面投影及有限期旧接口兼容 | 只输出受限 DTO，不把宿主对象或文件路径交给页面 |
| `unified_profile_contract.py` | 跨插件统一画像 DTO 与契约校验 | 改字段时同步检查契约测试和对接方 |

## 目录职责

| 目录 | 内容 |
| --- | --- |
| `core/` | 记忆领域、存储、检索、摘要、权限、来源、桥接与维护实现 |
| `pages/记忆面板/` | 标准管理界面、放映馆界面、静态资源和演示档案 |
| `data/` | 本地工作区产生的配置和模板，排除插件发布；AstrBot 运行时数据库位于 `StarTools.get_data_dir()` 返回的位置 |
| `tests/` | 单元、异步集成、权限回归、契约和页面后端测试 |
| `benchmarks/` | 可重复的离线精度审计与召回评测入口 |
| `scripts/` | 面向具体性能、查询计划和模型数据的开发期探针 |
| `docs/contracts/` | 查询工具的版本化 Schema、示例和契约说明；部分运行模块会从这里加载契约文件 |
| `docs/evaluations/` | 评测数据与运行结果，不作为运行时代码或通过声明 |

## 核心模块

按修改目的寻找模块，避免所有新逻辑继续堆进服务类或数据库类：

| 需求 | 主要模块 |
| --- | --- |
| 插件生命周期、主链协调、工具入口 | `core/service.py`、`main.py` |
| 记忆结构、持久化、事务和迁移 | `core/models.py`、`core/store.py`、`core/memory_atom.py`、`core/memory_revision.py`、`core/memory_lifecycle.py` |
| 召回、权限过滤、向量搜索和注入 | `core/retrieval.py`、`core/vector_search.py`、`core/visibility.py`、`core/injection.py`、`core/context_orchestrator.py` |
| 来源原文、读取凭证、查询、语义片段依赖与撤回 | `core/source_capture.py`、`core/source_evidence.py`、`core/source_query.py`、`core/source_query_v2.py`、`core/source_discovery.py`、`core/source_semantic.py`、`core/source_watches.py`、`core/message_sources.py` |
| 事件聚合、同轮进度和查询便笺 | `core/event_query.py`、`core/query_session.py`、`core/query_notes.py` |
| 总结生成、批次预算、事实校验 | `core/summarizer.py`、`core/summary_batches.py` |
| 外部插件接口与画像投影 | `core/bridge.py`、`core/bot_personal_*`、`core/person_*`、`core/portrait*` |
| 审计、导入、运维和数据治理 | `core/audit.py`、`core/operations.py`、`core/chat_import.py`、`core/migration_*`、`core/provenance*` |

`core/service.py` 和 `core/store.py` 目前仍承担较多协调与兼容职责。低风险整理阶段保持其公开调用面和文件路径稳定；新增逻辑优先进入已有的领域模块。以后如需拆分这两个大文件，应按独立职责逐块提取，并用对应测试保护公开行为，不做整文件搬迁。

## 主要调用路径

```text
AstrBot event
  -> main.MemoryCompanionPlugin
  -> core.service.MemoryCompanionService
  -> retrieval / injection / summarizer / store

管理页请求
  -> page_api.PluginPageApi
  -> core.service / core.store
  -> pages/记忆面板 静态界面
```

运行数据目录由 AstrBot 提供；当前工作区的 `data/` 和 `.workbuddy/` 属于本地文件，不参与发布。来源查询等模块通过 `docs/contracts/` 中的版本化文件读取请求或结果约定，因此打包时需要保留这些契约文件。

## 验证

不依赖 AstrBot 的离线评测可在系统 Python 中运行：

```powershell
python -X utf8 -m unittest tests.test_recall_evaluation
python -X utf8 -m benchmarks.audit_memory_precision
python -X utf8 -m benchmarks.run_recall_evaluation synthetic --decoys 40
```

涉及 AstrBot 或 Quart 的测试使用 AstrBot 自带 Python，并把 AstrBot `backend/app` 加入模块搜索路径：

```powershell
$AstrBotPython = Join-Path $env:USERPROFILE ".astrbot\backend\python\python.exe"
$AstrBotApp = Join-Path $env:USERPROFILE ".astrbot\backend\app"
& $AstrBotPython -X utf8 -c "import sys, pytest; sys.path.insert(0, r'$AstrBotApp'); raise SystemExit(pytest.main(['-q', 'tests']))"
```

聚焦验证时，把最后一个参数改为具体测试文件，例如 `tests/test_source_capture.py` 或 `tests/test_vector_search.py`。如果系统 Python 已安装 pytest，也可以用它运行不导入 AstrBot 的独立测试。

## 低风险整理约定

1. 保持 AstrBot 入口、插件元数据、配置 Schema、页面路由和外部桥接名稳定。
2. 移动文件前，先检查 `Path(__file__)`、契约加载路径、静态资源路由及包内相对导入。
3. 新的可独立测试能力放入 `core/` 的领域模块；`service.py` 负责协调，不复制存储或权限规则。
4. 文档、契约、评测数据和运行代码分开放置；历史记录保留日期或版本，不冒充现行接口。
5. 本地数据库、临时截图和工作台文件不属于插件发布目录；整理源码时不自动删除或覆盖它们。
