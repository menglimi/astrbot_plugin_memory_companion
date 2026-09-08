# 记忆提议通道第一轮升级

> 导航：[设计总纲](../../astrbot_plugin_private_companion/docs/FRAMEWORK_DESIGN.md) / [主题目录](../../astrbot_plugin_private_companion/docs/FRAMEWORK_DESIGN_INDEX.md)。定位：旧实现演进提案；供参考适配器映射，标准接口以主题目录所列记忆契约为准。

本轮把主动记忆写入从“固定字段直接落库”改为一个轻量的 `MemoryProposal` 通道。模型可以表达事实置信度、长期价值、保留倾向、有效时间和证据引用，运行时仍负责作用域、隐私、长度和状态安全。

## 写入语义

- `confidence` 和 `importance` 只作为模型判断，统一限制在 `0..1`。
- `durability` 支持 `ephemeral`、`short`、`normal`、`durable`、`pinned`，非法值回退到 `normal`。
- `valid_from` / `valid_to` 用于临时事实；非法 `validity_status` 会进入 `quarantined`，避免错误状态被召回。
- `evidence_refs` 和 `rationale` 写入受限的元数据，便于审计，不把原始提示词或整段对话当作记忆内容。
- 置信度低于 `0.55` 的提议仍保存为候选，但状态是 `pending` / `short_term_candidate`，由检索配置和后续治理决定是否呈现。
- `requested_persistence=false` 表示模型撤回长期写入意图，运行时返回 `state=skipped` 且 `ok=false`，不会创建记忆记录。

## 兼容性

旧的 `content + note_type` 调用保持不变；新增字段均为可选。没有关键词表，也没有要求模型输出内部标签。

## 验证场景

1. 明确偏好：`用户喜欢在周末跑步`，高置信度后进入稳定记忆。
2. 临时计划：带 `valid_to` 的约定，到期后由生命周期查询自动排除。
3. 不确定转述：低置信度进入候选状态，不直接影响正常回复。
4. 非法状态或超范围分数：运行时清洗并安全降级。
