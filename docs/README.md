# 记忆领域设计稿

先读陪伴核心的[新框架设计总纲](../../astrbot_plugin_private_companion/docs/FRAMEWORK_DESIGN.md)，再从[设计主题目录](../../astrbot_plugin_private_companion/docs/FRAMEWORK_DESIGN_INDEX.md)进入记忆的领域契约、外部接口、状态机和验收设计。

本目录的领域材料：

- [记忆精度专项审查与设计](./MEMORY_PRECISION_REVIEW_20260906.md)：证据级召回、权限过滤、事实更新和评测要求。
- [记忆提议通道第一轮升级](./MEMORY_PROPOSAL_UPGRADE_20260907.md)：`MemoryProposal` 写入通道和兼容策略。
- [记忆参考适配器设计 v0](./MEMORY_ADAPTER_DESIGN_V0.md)：现有入口到标准能力的映射、注册/卸载、事务缺口与第三方验收边界。

领域稿只约束记忆事实、证据、生命周期和检索；跨插件作用域、能力协商和主动编排以公共契约为准。精度审查和旧通道升级是设计来源，参考适配器是待验证的接入方案；当前不代表完整 SDK 或可靠 Writer 已实现。
