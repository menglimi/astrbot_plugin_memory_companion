# 本轮可选理解：memory.local-query-session.v2

2026-09-14，B1/B2 已有局部 C/R，B3 已完成隔离模型和本地成本对照；尚未加载生产宿主。详见[设计](../../../../../astrbot_plugin_private_companion/docs/MEMORY_QUERY_SESSION_DESIGN_V0.md#query-relation-package-b)和[验证记录](../../../../../astrbot_plugin_private_companion/docs/evaluations/S3_QUERY_RELATION_20260914.md)。来源有效只说明材料可读，不认证模型的解释正确。

## 接入

`MemoryCompanionService.tool_query_v2(event, operation, parameters, query_note=...)` 对应[请求 Schema](./schemas/request.schema.json)和[结果 Schema](./schemas/result.schema.json)。[请求示例](./examples/requests.json)及[空状态结果](./examples/result-empty.json)可直接做格式验证。原 `tool_query` 继续返回 query-session v1，原 owner 工具继续返回各自结果类型。

模型仍用原工具名称。`enable_query_progress` 与 `memory_tools.enable_query_notes` 同时开启、原 sources handler 支持参数且当前请求具备 status 绑定时，仅在本次请求副本上投影新格式：

- `memory_companion_sources` 可随原查询携带 `query_note`，经 `query_for_model` 返回 v2。
- `memory_companion_query` 只提供 status；`parameters.note_ids` 可选择要回看的便笺，省略时返回当前有效便笺的有界视图。
- recall/navigate/events 保留 A 的接法。关闭便笺回到 A；关闭进度回到原 owner 结果，状态入口不可用。未提供的新参数明确拒绝，不静默当作 v1 接受。

## 输入与独立回执

| 字段 | 内容 |
| --- | --- |
| `text` | 非空的简短理解，最多 800 字符，不含 NUL；无需固定话题或关系标签 |
| `evidence` | 1–6 个此前已返回的 `source_ref` / `source_version`；只能引用本轮有效时间线片段 |
| `replaces` | 可省略，最多 6 个旧便笺 ID；修改产生新 ID，不覆盖原版 |

输入整体最多 6 KiB。程序在执行下一查询前接受便笺，不能引用该查询尚未返回的内容。它绑定服务记录的实际片段、来源/权限 revision、轮次、人格、实例代际和原期限；不重新查全文或调用模型。

v2 中 `result` 是原查询结果，`progress` 是 A 的进度，`note_receipt` 独立表示 `not_submitted/accepted/reused/rejected/unavailable`，`notes` 是当前便笺可用状态。原查询参数有效且宿主可解码时，便笺格式/引用/容量错误不抹去查询结果；反过来，重复或额度拒绝的查询也可携带被接受的便笺，整体 `ok` 仍表示查询结果。未绑定、关闭或非法 operation 属于入口拒绝。

便笺以 `semantic_status=model_interpretation` 和 `source_status=receipts_valid` 分开表达。常规查询只返回短回执及数量，不重复输出正文；status 才返回选中且当前有效的正文、引用及已读区间。进度视图失败时保留原查询结果，已接受回执仅代表提交时的事实，不能据此推断当下仍可回看。

## 生命周期与资源

同文本、同引用版本/原期限、同替换目标的重试复用原回执；同义不同文字不自动合并。并发替换同一不可变 ID 时返回 `note_replacement_conflict`，无关查询推进 A revision 不阻止更新。

任一依据过期、修订或撤权后，整条便笺停止重发正文和引用；重新读取来源不会复活旧便笺。回看、编辑和重试不延长原来源 120 秒期限，状态约 600 秒的保留期不增加读取权限。换轮、换人格或实例重建不能复用旧绑定。便笺不写长期记忆，不跨重启恢复。

便笺与已结束查询操作共同使用 16 KiB 内存日志，各最多 24 条。优先省略失效便笺，再省略旧操作和旧便笺，保留累计计量和省略数；整条省略，不剪断结论。`progress + note_receipt + notes` 共用普通 900 字符、status 12000 字符展示预算，原 owner `result` 不截短。status 不增加检索步骤，但模型往返及输出仍有成本。

Host 的现有插件钩子不能证明压缩之后每次最终模型请求包含哪些原文，故 `current_context=unknown`。实际 AstrBot 压缩器的隔离夹具验证了同轮 status 回看和原句补读；未证明生产自动恢复或从在途请求删除旧材料。

## 验证

`tests/test_query_notes.py` 新增 23 项，涵盖成对格式、真实原生 handler/partial 绑定、开关兼容、双回执、并发/取消、失效隔离、容量与真实压缩器夹具。相关集合分次去重 173 项通过，最后子集 69 项、14 subtests 通过。

40 组本地对照，带便笺查询相对 A 的逐组额外耗时中位数 0.456 ms。24 个真实模型样本共 64 次请求、56 次工具调用，未提交或回看便笺；因此只取得启用开销与既有查询的对照，未取得自主便笺收益证据。程序通过不代表整条模型答案通过，详见独立评阅。
