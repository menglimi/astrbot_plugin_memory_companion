# C2c-1 来源片段维护增量 · 2026-10-08

本文记录 C2c 设计中的确定性来源维护切片。范围是片段/邻近窗口构造、历史扫描 checkpoint、来源变更 dirty 与写入前围栏；embedding worker、来源发现和 query-session v3 在后续切片交付，本文件不重复评估那些能力。

## 实现边界

- generation 注册时固定配置 hash 和起始来源修订。配置包含 provider/model/编码/处理/分片/窗口版本与显式构建范围；generation 配置不能原地修改。
- 历史扫描以 `timeline.id` 做 keyset 游标，页大小有界。owner 回调与构建范围在返回候选前逐行检查；候选不返回正文。checkpoint 记录 generation 起点和扫描是否完成。
- 扫描活跃期间，timeline insert/update/delete 仍通过独立的 semantic dirty 和顺序变更日志记录。扫描游标已越过的新旧时间插入不会进入已扫页，但仍有后续 dirty 可处理。
- 每个顺序变化保留旧/新 owner 分区和时间位置。展开日志时，在旧/新位置分别定位当前最近的前后来源，把受影响来源加入本 generation 的 semantic dirty，并使以这些来源为锚的窗口文档 stale。原文直接变更会按反向依赖使已有投影 stale。
- dirty 只按完全匹配的 change sequence 确认；来源仍有未展开的顺序变更时，不能确认其 semantic dirty。词法查询 dirty 不参与此过程。
- 窗口构造保留锚点与邻居各自的 Unicode 字符 span，并按总字符预算裁切邻居。投影写入时重验 generation/config、全局 source revision、构建范围、owner callback、每个 source_version、span、拼接文本和窗口最近邻。

## 最小回归

本切片新增用例覆盖稳定扫描与游标前旧时间插入、owner 拒绝、限定构建范围、dirty 合并与版本确认、退休 generation 拒绝迟到写入、依赖正文 hash、窗口 span 与邻接变化，以及插入/删除/改时间后的邻居重入队。

使用 AstrBot 自带 Python 运行来源语义、来源查询、source-query v1 契约和来源捕获回归：

```powershell
C:\Users\99505\.astrbot\backend\python\python.exe -X utf8 -m pytest -q tests\test_source_semantic.py tests\test_source_query.py tests\test_source_query_contract.py tests\test_source_capture.py --disable-warnings --maxfail=1
```

结果：**78 passed**；`py_compile` 通过。当前没有对大库吞吐、SQL/WAL/RSS、dirty 积压或 provider 网络调用做性能和运行验收。

## 本文件未覆盖

- 这一维护切片不覆盖后台 worker、Provider 调用和前台查询；这些内容分别见 C2c-2 worker 评估、来源发现回归和 query-session v3 契约。
- 真实陌生问法、吞吐/锁等待/WAL/RSS 与宿主/生产验收仍需单独执行。

因此本文只证明 C2c-1 维护基础的确定性行为；不能单独推导完整 v2 记忆设计或生产可用性结论。
