from __future__ import annotations

import copy
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ConfigView
from .models import clean_text


VALID_PERFORMANCE_PROFILES = ("auto", "eco", "balanced", "turbo", "compat")
CONCRETE_PERFORMANCE_TIERS = ("eco", "balanced", "turbo", "compat")

# Sentinels for the 4 SQLite engine keys inside `performance.*`:
# when a field equals its sentinel, it dynamically tracks the active tier.
SQLITE_SENTINELS: dict[str, Any] = {
    "performance.sqlite_cache_size_mb": 0,
    "performance.sqlite_mmap_size_mb": -1,
    "performance.sqlite_read_pool_size": 0,
    "performance.sqlite_synchronous": "auto",
}

# Anything >= 1 PiB in cgroup memory limit files means "unlimited" on Linux kernels.
_CGROUP_UNLIMITED_THRESHOLD_BYTES = 1 << 50

_HARDWARE_CACHE: HostHardwareInfo | None = None


@dataclass(frozen=True)
class HostHardwareInfo:
    """Detected host / container hardware resources used for adaptive tuning."""

    host_memory_mb: int | None
    cgroup_memory_mb: int | None
    effective_memory_mb: int | None
    memory_source: str
    cpu_count: int
    is_32bit: bool
    recommended_tier: str
    recommendation_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "host_memory_mb": self.host_memory_mb,
            "cgroup_memory_mb": self.cgroup_memory_mb,
            "effective_memory_mb": self.effective_memory_mb,
            "memory_source": self.memory_source,
            "cpu_count": self.cpu_count,
            "is_32bit": self.is_32bit,
            "recommended_tier": self.recommended_tier,
            "recommendation_reason": self.recommendation_reason,
        }


@dataclass(frozen=True)
class PerformanceTierSpec:
    """User-facing metadata for one of the 5 unified performance tiers."""

    id: str
    label: str
    badge: str
    tagline: str
    target_scene: str
    summary: str
    highlights: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "badge": self.badge,
            "tagline": self.tagline,
            "target_scene": self.target_scene,
            "summary": self.summary,
            "highlights": list(self.highlights),
        }


@dataclass(frozen=True)
class PerformanceParamSpec:
    """Metadata and validation constraints for one tunable performance parameter."""

    key: str
    module: str
    field: str
    group: str
    group_label: str
    label: str
    value_type: str  # "int" | "float" | "bool" | "enum"
    unit: str
    display_scale: int
    min_value: float | None
    max_value: float | None
    step: float | None
    options: tuple[tuple[str, str], ...]
    hot_reload: bool
    schema_default: Any
    summary: str
    up_effect: str
    down_effect: str
    search_aliases: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "module": self.module,
            "field": self.field,
            "group": self.group,
            "group_label": self.group_label,
            "label": self.label,
            "value_type": self.value_type,
            "unit": self.unit,
            "display_scale": self.display_scale,
            "min": self.min_value,
            "max": self.max_value,
            "step": self.step,
            "options": [{"value": v, "label": lbl} for v, lbl in self.options],
            "hot_reload": self.hot_reload,
            "effect_scope": "保存后立即生效" if self.hot_reload else "下次重启生效",
            "summary": self.summary,
            "up_effect": self.up_effect,
            "down_effect": self.down_effect,
            "search_aliases": list(self.search_aliases),
        }


PERFORMANCE_TIER_SPECS: tuple[PerformanceTierSpec, ...] = (
    PerformanceTierSpec(
        id="auto",
        label="智能自动",
        badge="默认推荐",
        tagline="自动识别机器与容器内存，按需分配缓存",
        target_scene="不知道选哪一档时直接用它，换机器或扩容后也能自动适配",
        summary="自动探测主机物理内存与 Docker/cgroup 限额，低配走省资源、常规走均衡、大内存走高性能。",
        highlights=("自动感知 Docker 内存上限", "32 位环境自动禁用 mmap", "防内存溢出自动限幅"),
    ),
    PerformanceTierSpec(
        id="eco",
        label="省资源",
        badge="1–2G 云服 / 容器",
        tagline="压低内存占用，杜绝低配机器卡死或 OOM",
        target_scene="1–2G 轻量云服、树莓派、内存紧张的 Docker 容器或小规格 VPS",
        summary="向量改用半精度省 75% 空间、关闭内存映射与启动预热、缩小页缓存与并发路数。",
        highlights=("向量半精度省 75% 空间", "关闭 mmap 与启动预热", "极低常驻内存占用"),
    ),
    PerformanceTierSpec(
        id="balanced",
        label="均衡推荐",
        badge="4–8G 日常主机",
        tagline="速度、内存占用与稳定性三者兼顾",
        target_scene="4–8G 常见云服务器、轻薄本或日常家用电脑",
        summary="保持 float32 标准精度，开启 256MB 向量快照缓存、32MB 页缓存与适度并发读池。",
        highlights=("标准精度无损召回", "日常聊天毫秒级响应", "内存占用克制平稳"),
    ),
    PerformanceTierSpec(
        id="turbo",
        label="高性能",
        badge="16G+ 桌面机 / 大库",
        tagline="充分缓存热记忆与并行查询，大库也丝滑",
        target_scene="16G+ 台式机/高配服务器、万条以上大记忆库、多群高并发同时聊",
        summary="拉满 SQLite 页缓存、最高 1GB 内存映射与 6–12 路并行读连接池，显著提速大库与多群并发。",
        highlights=("最高 1GB 内存映射热读", "6–12 路并发读池零排队", "后台向量补齐提速"),
    ),
    PerformanceTierSpec(
        id="compat",
        label="慢盘 / 稳妥兼容",
        badge="机械硬盘 / NAS / 弱网",
        tagline="减少磁盘突刺并放宽等待预算，老硬盘更稳",
        target_scene="老旧机械硬盘、NAS 网络盘、虚拟化磁盘抖动明显或网络较慢的环境",
        summary="关闭 mmap、采用 FULL 严格落盘保护数据安全，并把回复等待预算放宽到 5 秒减少偶发漏注入。",
        highlights=("严格落盘防断电损坏", "回复等待预算放宽至 5 秒", "关闭预热避免开机抢盘"),
    ),
)

PERFORMANCE_TIER_BY_ID: dict[str, PerformanceTierSpec] = {
    spec.id: spec for spec in PERFORMANCE_TIER_SPECS
}

PERFORMANCE_GROUPS: tuple[dict[str, str], ...] = (
    {"id": "sqlite", "label": "数据库引擎", "desc": "控制 SQLite 页缓存、内存映射、并发读连接与落盘安全策略"},
    {"id": "retrieval", "label": "向量与检索", "desc": "控制记忆向量精度、内存快照大小、冷启动预热与后台向量并发"},
    {"id": "latency", "label": "回复等待保护", "desc": "控制单轮聊天的记忆检索等待上限，避免慢盘或慢网时误判超时"},
    {"id": "maintenance", "label": "后台维护与启动", "desc": "控制 WAL 日志清理门槛与插件刚启动时的错峰等待时间"},
)

PERFORMANCE_PARAMS: tuple[PerformanceParamSpec, ...] = (
    # ---- Group 1: sqlite ----
    PerformanceParamSpec(
        key="performance.sqlite_cache_size_mb",
        module="performance",
        field="sqlite_cache_size_mb",
        group="sqlite",
        group_label="数据库引擎",
        label="数据库页缓存",
        value_type="int",
        unit="MB",
        display_scale=1,
        min_value=4,
        max_value=256,
        step=4,
        options=(),
        hot_reload=True,
        schema_default=0,
        summary="SQLite 用来常驻热数据页的内存大小（受可用内存 10% 防爆上限保护）。",
        up_effect="调大：翻历史记忆、频繁切换人物与群聊更少读硬盘，速度更快；但常驻内存会略增。",
        down_effect="调小：更省内存，适合 1–2G 小机器；但大记忆库连续查询时读盘会变多。",
        search_aliases=("页缓存", "cache_size", "sqlite缓存", "省内存", "低配机", "数据库缓存"),
    ),
    PerformanceParamSpec(
        key="performance.sqlite_mmap_size_mb",
        module="performance",
        field="sqlite_mmap_size_mb",
        group="sqlite",
        group_label="数据库引擎",
        label="内存映射上限（mmap）",
        value_type="int",
        unit="MB",
        display_scale=1,
        min_value=0,
        max_value=2048,
        step=64,
        options=(),
        hot_reload=True,
        schema_default=-1,
        summary="把数据库文件直接映射到系统内存页缓存；设为 0 即关闭（受可用内存 25% 限幅，32 位自动关）。",
        up_effect="调大：SSD 大记忆库读取减少系统调用，响应更丝滑；需确保物理内存充足。",
        down_effect="调小或设为 0：彻底避免低配云服/机械硬盘/NAS 上虚拟内存抖动，更稳妥。",
        search_aliases=("内存映射", "mmap", "mmap_size", "机械硬盘", "NAS", "卡顿"),
    ),
    PerformanceParamSpec(
        key="performance.sqlite_read_pool_size",
        module="performance",
        field="sqlite_read_pool_size",
        group="sqlite",
        group_label="数据库引擎",
        label="并发读连接池数",
        value_type="int",
        unit="路",
        display_scale=1,
        min_value=1,
        max_value=12,
        step=1,
        options=(),
        hot_reload=True,
        schema_default=0,
        summary="面板刷新与多个群同时聊天时，并行读取数据库的只读连接数上限。",
        up_effect="调大：多群同时触发回忆或打开记忆面板时不排队、不互相卡住；每个连接会多占少量缓存内存。",
        down_effect="调小：降低并发连接与内存占用；群很多时同时查询可能需要短暂排队。",
        search_aliases=("连接池", "读连接池", "并发读", "read_pool", "多群卡顿"),
    ),
    PerformanceParamSpec(
        key="performance.sqlite_synchronous",
        module="performance",
        field="sqlite_synchronous",
        group="sqlite",
        group_label="数据库引擎",
        label="落盘同步策略",
        value_type="enum",
        unit="",
        display_scale=1,
        min_value=None,
        max_value=None,
        step=None,
        options=(
            ("NORMAL", "NORMAL（速度与安全兼顾 · 推荐）"),
            ("FULL", "FULL（每次提交强刷磁盘 · 防断电）"),
        ),
        hot_reload=True,
        schema_default="auto",
        summary="控制每次写记忆后是否立即等待硬盘物理刷盘（WAL 模式下 NORMAL 已对进程崩溃安全）。",
        up_effect="选 FULL：即使整机突然断电也不丢最近写入，适合老机械盘/不稳定电源；但写入耗时稍高。",
        down_effect="选 NORMAL：写入快、不拖慢聊天响应，绝大多数电脑与云服的首选。",
        search_aliases=("落盘", "同步策略", "synchronous", "机械硬盘", "防断电", "写盘"),
    ),
    # ---- Group 2: retrieval ----
    PerformanceParamSpec(
        key="retrieval_advanced.vector_precision",
        module="retrieval_advanced",
        field="vector_precision",
        group="retrieval",
        group_label="向量与检索",
        label="向量存储精度",
        value_type="enum",
        unit="",
        display_scale=1,
        min_value=None,
        max_value=None,
        step=None,
        options=(
            ("float32", "float32（标准精度 · 无损推荐）"),
            ("float16", "float16（半精度省流 · 体积直降 75%）"),
        ),
        hot_reload=True,
        schema_default="float32",
        summary="控制新写入和内存载入的记忆向量精度；切换后旧数据依然兼容，可配合「一键瘦身」批量转码。",
        up_effect="选 float32：语义检索精度完全无损，空间也比旧版少一半，适合 4G+ 主机。",
        down_effect="选 float16：向量内存与数据库体积直接再减半（比旧版省 75%），1–2G 低配服极推荐。",
        search_aliases=("向量精度", "半精度", "float16", "float32", "省内存", "瘦身"),
    ),
    PerformanceParamSpec(
        key="retrieval_advanced.vector_snapshot_cache_mb",
        module="retrieval_advanced",
        field="vector_snapshot_cache_mb",
        group="retrieval",
        group_label="向量与检索",
        label="向量快照缓存上限",
        value_type="int",
        unit="MB",
        display_scale=1,
        min_value=64,
        max_value=2048,
        step=64,
        options=(),
        hot_reload=True,
        schema_default=512,
        summary="向量检索时缓存在内存里的数值快照上限，命中后下一轮直接复用免全库扫描（受内存 30% 防爆上限保护）。",
        up_effect="调大：海量记忆下连续语义检索几乎秒回，减少反复读库；会相应增加常驻内存。",
        down_effect="调小：立刻压低内存峰值，不影响能想起的内容，只是超出缓存的部分需要现读磁盘。",
        search_aliases=("向量缓存", "快照缓存", "vector_snapshot_cache_mb", "省内存", "大内存"),
    ),
    PerformanceParamSpec(
        key="retrieval_advanced.startup_vector_warmup_enabled",
        module="retrieval_advanced",
        field="startup_vector_warmup_enabled",
        group="retrieval",
        group_label="向量与检索",
        label="启动后台预热向量库",
        value_type="bool",
        unit="",
        display_scale=1,
        min_value=None,
        max_value=None,
        step=None,
        options=(),
        hot_reload=False,
        schema_default=True,
        summary="启动后在后台提前把本地记忆向量读进内存快照（不调任何付费 API，零费用）。",
        up_effect="开启：刚重启后的第一句聊天就能直接命中热记忆，大幅减少首轮冷启动超时。",
        down_effect="关闭：刚启动时几乎不占内存和磁盘 IO，适合 1–2G 低配机或慢机械硬盘。",
        search_aliases=("启动预热", "向量预热", "冷启动", "startup_vector_warmup_enabled", "开机卡顿"),
    ),
    PerformanceParamSpec(
        key="retrieval_advanced.embedding_background_concurrency",
        module="retrieval_advanced",
        field="embedding_background_concurrency",
        group="retrieval",
        group_label="向量与检索",
        label="后台向量补齐并发",
        value_type="int",
        unit="路",
        display_scale=1,
        min_value=1,
        max_value=8,
        step=1,
        options=(),
        hot_reload=True,
        schema_default=2,
        summary="新记忆生成和历史补索引时，后台同时请求 Embedding 模型的最大并发数。",
        up_effect="调大：导入大量聊天或换向量模型后，补索引进度明显加快；但可能触发部分中转 API 限流。",
        down_effect="调小：更温和，不易触发接口 429 限速，也不和日常聊天抢网络带宽。",
        search_aliases=("向量并发", "补索引并发", "embedding_background_concurrency", "限流"),
    ),
    # ---- Group 3: latency ----
    PerformanceParamSpec(
        key="memory_injection.hook_request_budget_seconds",
        module="memory_injection",
        field="hook_request_budget_seconds",
        group="latency",
        group_label="回复等待保护",
        label="回复前记忆等待上限",
        value_type="float",
        unit="秒",
        display_scale=1,
        min_value=0.5,
        max_value=8.0,
        step=0.1,
        options=(),
        hot_reload=True,
        schema_default=1.0,
        summary="每轮发消息前最多等插件本地检索多久（不含外部向量/重排 API 等待）；超时直接放行回复不卡死。",
        up_effect="调大（最高 8 秒）：机械硬盘、弱网或大记忆库冷启动时更不容易漏注入记忆；极端卡顿时回复会多等一会儿。",
        down_effect="调小：保证机器人永远秒回不卡顿；但磁盘很忙时更容易跳过本轮记忆注入。",
        search_aliases=("钩子预算", "超时预算", "等待上限", "hook_request_budget_seconds", "卡顿", "漏记忆"),
    ),
    PerformanceParamSpec(
        key="retrieval_advanced.recall_latency_budget_ms",
        module="retrieval_advanced",
        field="recall_latency_budget_ms",
        group="latency",
        group_label="回复等待保护",
        label="召回精排时间预算",
        value_type="int",
        unit="毫秒",
        display_scale=1,
        min_value=500,
        max_value=8000,
        step=100,
        options=(),
        hot_reload=True,
        schema_default=1800,
        summary="单轮记忆检索的内部耗时预算，超出后会跳过耗时的精排模型直接用本地排序返回。",
        up_effect="调大：精排模型有更充裕的时间完成排序，复杂长问题的回忆准确度更稳；网络慢时会略增加回复延迟。",
        down_effect="调小：回复更快、更果断地降级到本地排序，不因精排慢而拖延聊天。",
        search_aliases=("召回预算", "精排预算", "recall_latency_budget_ms", "延迟", "卡顿"),
    ),
    # ---- Group 4: maintenance ----
    PerformanceParamSpec(
        key="maintenance.wal_checkpoint_min_bytes",
        module="maintenance",
        field="wal_checkpoint_min_bytes",
        group="maintenance",
        group_label="后台维护与启动",
        label="WAL 日志清理阈值",
        value_type="int",
        unit="MB",
        display_scale=1024 * 1024,
        min_value=2 * 1024 * 1024,
        max_value=128 * 1024 * 1024,
        step=1024 * 1024,
        options=(),
        hot_reload=True,
        schema_default=8 * 1024 * 1024,
        summary="SQLite 临时写入日志（-wal）长到多大时，后台自动把它合并回主库并截断瘦身。",
        up_effect="调大：减少后台合并磁盘的频率，高并发写入更顺；但 -wal 临时文件占用会稍大。",
        down_effect="调小：更勤快地回收 -wal 体积，硬盘更清爽；低配小盘更安心。",
        search_aliases=("WAL", "wal截断", "日志阈值", "wal_checkpoint_min_bytes", "释放空间"),
    ),
    PerformanceParamSpec(
        key="startup.background_grace_seconds",
        module="startup",
        field="background_grace_seconds",
        group="maintenance",
        group_label="后台维护与启动",
        label="启动后台错峰宽限期",
        value_type="int",
        unit="秒",
        display_scale=1,
        min_value=0,
        max_value=600,
        step=10,
        options=(),
        hot_reload=False,
        schema_default=60,
        summary="插件刚启动后先等多少秒，再陆续拉起后台整理、预热与维护任务，避开开机高峰。",
        up_effect="调大：重启 AstrBot 时 CPU 和硬盘更安静，防止机械盘或低配机启动拥堵。",
        down_effect="调小：启动后更快进入后台预热与整理状态，适合高配 SSD 机器。",
        search_aliases=("启动宽限期", "错峰启动", "background_grace_seconds", "开机卡顿"),
    ),
)

PERFORMANCE_PARAM_BY_KEY: dict[str, PerformanceParamSpec] = {
    spec.key: spec for spec in PERFORMANCE_PARAMS
}


def _read_first_line(path: str | Path) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.readline().strip()
    except OSError:
        return ""


def _detect_cgroup_memory_mb(
    *,
    v2_path: str | Path = "/sys/fs/cgroup/memory.max",
    v1_path: str | Path = "/sys/fs/cgroup/memory/memory.limit_in_bytes",
) -> tuple[int | None, str]:
    """Detect Linux container memory ceiling from cgroup v2 or v1."""
    raw_v2 = _read_first_line(v2_path)
    if raw_v2 and raw_v2.lower() != "max":
        try:
            limit_bytes = int(raw_v2)
            if 0 < limit_bytes < _CGROUP_UNLIMITED_THRESHOLD_BYTES:
                return max(1, limit_bytes // (1024 * 1024)), "cgroup_v2"
        except ValueError:
            pass

    raw_v1 = _read_first_line(v1_path)
    if raw_v1:
        try:
            limit_bytes = int(raw_v1)
            if 0 < limit_bytes < _CGROUP_UNLIMITED_THRESHOLD_BYTES:
                return max(1, limit_bytes // (1024 * 1024)), "cgroup_v1"
        except ValueError:
            pass
    return None, ""


def _detect_cgroup_cpu_limit(
    *,
    v2_path: str | Path = "/sys/fs/cgroup/cpu.max",
    v1_quota_path: str | Path = "/sys/fs/cgroup/cpu/cpu.cfs_quota_us",
    v1_period_path: str | Path = "/sys/fs/cgroup/cpu/cpu.cfs_period_us",
) -> int | None:
    """Detect Linux container CPU quota ceiling if explicitly constrained."""
    raw_v2 = _read_first_line(v2_path)
    if raw_v2:
        parts = raw_v2.split()
        if len(parts) >= 2 and parts[0].lower() != "max":
            try:
                quota = int(parts[0])
                period = int(parts[1])
                if quota > 0 and period > 0:
                    return max(1, int(math.ceil(quota / period)))
            except ValueError:
                pass

    raw_quota = _read_first_line(v1_quota_path)
    raw_period = _read_first_line(v1_period_path)
    if raw_quota and raw_period:
        try:
            quota = int(raw_quota)
            period = int(raw_period)
            if quota > 0 and period > 0:
                return max(1, int(math.ceil(quota / period)))
        except ValueError:
            pass
    return None


def _detect_host_memory_mb() -> tuple[int | None, str]:
    """Best-effort stdlib detection of host physical RAM in MiB."""
    try:
        if os.name == "nt":
            import ctypes

            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return max(1, int(status.ullTotalPhys // (1024 * 1024))), "windows"
        elif os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo", "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            return max(1, int(parts[1]) // 1024), "proc_meminfo"
                        break
        elif hasattr(os, "sysconf"):
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            if isinstance(pages, int) and isinstance(page_size, int) and pages > 0 and page_size > 0:
                return max(1, int((pages * page_size) // (1024 * 1024))), "sysconf"
    except Exception:
        pass
    return None, "unknown"


def _detect_host_cpu_count() -> int:
    try:
        count = os.cpu_count()
        if isinstance(count, int) and count > 0:
            return count
    except Exception:
        pass
    return 2


def _format_mem_gb(mem_mb: int | None) -> str:
    if mem_mb is None or mem_mb <= 0:
        return "未知内存"
    if mem_mb < 1024:
        return f"{mem_mb} MiB"
    return f"{mem_mb / 1024.0:.1f} GiB"


def _recommend_tier_from_hardware(
    effective_memory_mb: int | None,
    cpu_count: int,
    *,
    memory_source: str,
    is_32bit: bool,
) -> tuple[str, str]:
    mem_text = _format_mem_gb(effective_memory_mb)
    source_label = {
        "cgroup_v2": "容器 cgroup v2 限额",
        "cgroup_v1": "容器 cgroup v1 限额",
        "windows": "主机物理内存",
        "proc_meminfo": "主机物理内存",
        "sysconf": "主机物理内存",
    }.get(memory_source, "内存探测")

    if effective_memory_mb is not None and effective_memory_mb <= 2560:
        tier = "eco"
        reason = (
            f"检测到可用内存约 {mem_text}（{source_label}，{cpu_count} 核 CPU），"
            "内存较紧张，推荐「省资源」档位以降低常驻占用并防范 OOM。"
        )
    elif effective_memory_mb is not None and effective_memory_mb > 10240:
        tier = "turbo"
        reason = (
            f"检测到可用内存约 {mem_text}（{source_label}，{cpu_count} 核 CPU），"
            "资源充裕，推荐「高性能」档位以充分缓存热记忆与并行响应多群。"
        )
    elif effective_memory_mb is not None:
        tier = "balanced"
        reason = (
            f"检测到可用内存约 {mem_text}（{source_label}，{cpu_count} 核 CPU），"
            "推荐「均衡推荐」档位，在响应速度与内存占用之间保持平稳。"
        )
    else:
        tier = "balanced"
        reason = (
            f"未能准确读取可用内存上限（检测到 {cpu_count} 核 CPU），"
            "默认推荐稳妥的「均衡推荐」档位。"
        )

    if is_32bit:
        reason += "（同时检测到 32 位运行环境，已自动关闭内存映射 mmap 以避免虚拟地址空间受限。）"
    return tier, reason


def detect_host_hardware(
    *,
    host_memory_mb: int | None = None,
    cgroup_memory_mb: int | None = None,
    cpu_count: int | None = None,
    is_32bit: bool | None = None,
    force_refresh: bool = False,
) -> HostHardwareInfo:
    """Detect host + container cgroup resources (cached when called with no overrides)."""
    global _HARDWARE_CACHE
    has_overrides = any(
        item is not None for item in (host_memory_mb, cgroup_memory_mb, cpu_count, is_32bit)
    )
    if not has_overrides and not force_refresh and _HARDWARE_CACHE is not None:
        return _HARDWARE_CACHE

    if host_memory_mb is None:
        detected_host_mb, host_source = _detect_host_memory_mb()
    else:
        detected_host_mb = max(1, int(host_memory_mb))
        host_source = "override"

    if cgroup_memory_mb is None:
        if os.name == "nt" or host_memory_mb is not None:
            detected_cg_mb, cg_source = (None, "")
        else:
            detected_cg_mb, cg_source = _detect_cgroup_memory_mb()
    else:
        detected_cg_mb = max(1, int(cgroup_memory_mb))
        cg_source = "cgroup_v2"

    if detected_host_mb is not None and detected_cg_mb is not None:
        if detected_cg_mb < detected_host_mb:
            effective_mb = detected_cg_mb
            mem_source = cg_source or "cgroup_v2"
        else:
            effective_mb = detected_host_mb
            mem_source = host_source
    elif detected_cg_mb is not None:
        effective_mb = detected_cg_mb
        mem_source = cg_source or "cgroup_v2"
    elif detected_host_mb is not None:
        effective_mb = detected_host_mb
        mem_source = host_source
    else:
        effective_mb = None
        mem_source = "unknown"

    if cpu_count is None:
        host_cpus = _detect_host_cpu_count()
        cg_cpus = None if os.name == "nt" else _detect_cgroup_cpu_limit()
        effective_cpus = max(1, min(host_cpus, cg_cpus) if cg_cpus else host_cpus)
    else:
        effective_cpus = max(1, int(cpu_count))

    env_32bit = (sys.maxsize <= 2**32) if is_32bit is None else bool(is_32bit)
    recommended_tier, reason = _recommend_tier_from_hardware(
        effective_mb,
        effective_cpus,
        memory_source=mem_source,
        is_32bit=env_32bit,
    )
    info = HostHardwareInfo(
        host_memory_mb=detected_host_mb,
        cgroup_memory_mb=detected_cg_mb,
        effective_memory_mb=effective_mb,
        memory_source=mem_source,
        cpu_count=effective_cpus,
        is_32bit=env_32bit,
        recommended_tier=recommended_tier,
        recommendation_reason=reason,
    )
    if not has_overrides:
        _HARDWARE_CACHE = info
    return info


def normalize_performance_profile(value: Any, *, default: str = "auto") -> str:
    text = clean_text(value, 32).lower()
    if text in VALID_PERFORMANCE_PROFILES:
        return text
    return default


def resolve_tier_defaults(
    effective_tier: str,
    hardware: HostHardwareInfo,
) -> dict[str, Any]:
    """Return the exact 12-parameter baseline for one concrete performance tier."""
    tier = effective_tier if effective_tier in CONCRETE_PERFORMANCE_TIERS else "balanced"
    cpus = max(1, int(hardware.cpu_count))
    ram_mb = hardware.effective_memory_mb

    if tier == "eco":
        defaults: dict[str, Any] = {
            "performance.sqlite_cache_size_mb": 8,
            "performance.sqlite_mmap_size_mb": 0,
            "performance.sqlite_read_pool_size": 2,
            "performance.sqlite_synchronous": "NORMAL",
            "retrieval_advanced.vector_precision": "float16",
            "retrieval_advanced.vector_snapshot_cache_mb": 64,
            "retrieval_advanced.startup_vector_warmup_enabled": False,
            "retrieval_advanced.embedding_background_concurrency": 1,
            "memory_injection.hook_request_budget_seconds": 2.0,
            "retrieval_advanced.recall_latency_budget_ms": 1200,
            "maintenance.wal_checkpoint_min_bytes": 4 * 1024 * 1024,
            "startup.background_grace_seconds": 90,
        }
    elif tier == "turbo":
        turbo_mmap = 0 if hardware.is_32bit else (1024 if (ram_mb is not None and ram_mb >= 20480) else 512)
        defaults = {
            "performance.sqlite_cache_size_mb": 64,
            "performance.sqlite_mmap_size_mb": turbo_mmap,
            "performance.sqlite_read_pool_size": max(6, min(12, cpus)),
            "performance.sqlite_synchronous": "NORMAL",
            "retrieval_advanced.vector_precision": "float32",
            "retrieval_advanced.vector_snapshot_cache_mb": 512,
            "retrieval_advanced.startup_vector_warmup_enabled": True,
            "retrieval_advanced.embedding_background_concurrency": 4,
            "memory_injection.hook_request_budget_seconds": 3.0,
            "retrieval_advanced.recall_latency_budget_ms": 2200,
            "maintenance.wal_checkpoint_min_bytes": 16 * 1024 * 1024,
            "startup.background_grace_seconds": 30,
        }
    elif tier == "compat":
        defaults = {
            "performance.sqlite_cache_size_mb": 16,
            "performance.sqlite_mmap_size_mb": 0,
            "performance.sqlite_read_pool_size": 2,
            "performance.sqlite_synchronous": "FULL",
            "retrieval_advanced.vector_precision": "float32",
            "retrieval_advanced.vector_snapshot_cache_mb": 128,
            "retrieval_advanced.startup_vector_warmup_enabled": False,
            "retrieval_advanced.embedding_background_concurrency": 1,
            "memory_injection.hook_request_budget_seconds": 5.0,
            "retrieval_advanced.recall_latency_budget_ms": 3000,
            "maintenance.wal_checkpoint_min_bytes": 4 * 1024 * 1024,
            "startup.background_grace_seconds": 120,
        }
    else:  # balanced
        balanced_mmap = 0 if hardware.is_32bit else 256
        defaults = {
            "performance.sqlite_cache_size_mb": 32,
            "performance.sqlite_mmap_size_mb": balanced_mmap,
            "performance.sqlite_read_pool_size": max(3, min(6, cpus)),
            "performance.sqlite_synchronous": "NORMAL",
            "retrieval_advanced.vector_precision": "float32",
            "retrieval_advanced.vector_snapshot_cache_mb": 256,
            "retrieval_advanced.startup_vector_warmup_enabled": True,
            "retrieval_advanced.embedding_background_concurrency": 2,
            "memory_injection.hook_request_budget_seconds": 3.0,
            "retrieval_advanced.recall_latency_budget_ms": 1800,
            "maintenance.wal_checkpoint_min_bytes": 8 * 1024 * 1024,
            "startup.background_grace_seconds": 60,
        }
    return defaults


def _coerce_param_value(spec: PerformanceParamSpec, raw_value: Any) -> Any:
    if spec.value_type == "bool":
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, str):
            return raw_value.strip().lower() in {"1", "true", "yes", "on", "开", "开启"}
        return bool(raw_value)
    if spec.value_type == "enum":
        text = clean_text(raw_value, 40)
        valid_values = {opt[0] for opt in spec.options}
        if text in valid_values:
            return text
        upper = text.upper()
        if upper in valid_values:
            return upper
        lower = text.lower()
        if lower in valid_values:
            return lower
        raise ValueError(f"参数「{spec.label}」的可选值必须是 {' / '.join(sorted(valid_values))}")
    if spec.value_type == "int":
        if isinstance(raw_value, bool):
            raise ValueError(f"参数「{spec.label}」必须是整数")
        try:
            parsed = int(round(float(raw_value)))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"参数「{spec.label}」必须是整数") from exc
        return parsed
    if spec.value_type == "float":
        if isinstance(raw_value, bool):
            raise ValueError(f"参数「{spec.label}」必须是数字")
        try:
            parsed = float(raw_value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"参数「{spec.label}」必须是数字") from exc
        if not math.isfinite(parsed):
            raise ValueError(f"参数「{spec.label}」必须是有效数字")
        return round(parsed, 2)
    return raw_value


def _is_sentinel_value(key: str, value: Any) -> bool:
    if key not in SQLITE_SENTINELS:
        return False
    sentinel = SQLITE_SENTINELS[key]
    if key == "performance.sqlite_synchronous":
        text = clean_text(value, 32).lower()
        return text in {"", "auto"}
    if isinstance(value, bool):
        return False
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return True
    if key == "performance.sqlite_mmap_size_mb":
        return parsed < 0
    return parsed <= int(sentinel)


def _clamp_param_value(
    spec: PerformanceParamSpec,
    requested: Any,
    hardware: HostHardwareInfo,
) -> tuple[Any, dict[str, Any] | None]:
    """Apply hard-range and RAM-relative Anti-OOM clamping; return (effective, clamp_notice)."""
    effective = requested
    reasons: list[str] = []

    if spec.value_type in {"int", "float"}:
        if spec.min_value is not None and effective < spec.min_value:
            effective = int(spec.min_value) if spec.value_type == "int" else float(spec.min_value)
            reasons.append(f"低于安全下限，已调整至最小值")
        if spec.max_value is not None and effective > spec.max_value:
            effective = int(spec.max_value) if spec.value_type == "int" else float(spec.max_value)
            reasons.append(f"超过安全上限，已调整至最大值")

        ram_mb = hardware.effective_memory_mb
        if spec.key == "performance.sqlite_cache_size_mb" and ram_mb is not None:
            ram_cap = max(4, min(256, int(ram_mb * 0.10)))
            if effective > ram_cap:
                effective = ram_cap
                reasons.append(
                    f"防爆内存保护：不能超过本机可用内存（{_format_mem_gb(ram_mb)}）的 10%，已限幅至 {ram_cap} MB"
                )
        elif spec.key == "performance.sqlite_mmap_size_mb":
            if hardware.is_32bit and effective > 0:
                effective = 0
                reasons.append("32 位运行环境虚拟地址空间受限，已自动关闭内存映射（mmap=0）")
            elif ram_mb is not None:
                ram_cap = min(2048, max(0, int(ram_mb * 0.25)))
                if effective > ram_cap:
                    effective = ram_cap
                    reasons.append(
                        f"防爆内存保护：不能超过本机可用内存（{_format_mem_gb(ram_mb)}）的 25%，已限幅至 {ram_cap} MB"
                    )
        elif spec.key == "retrieval_advanced.vector_snapshot_cache_mb" and ram_mb is not None:
            ram_cap = max(64, min(2048, int(ram_mb * 0.30)))
            if effective > ram_cap:
                effective = ram_cap
                reasons.append(
                    f"防爆内存保护：不能超过本机可用内存（{_format_mem_gb(ram_mb)}）的 30%，已限幅至 {ram_cap} MB"
                )

    if effective != requested and reasons:
        def _fmt_val(v: Any) -> str:
            if spec.display_scale > 1 and isinstance(v, (int, float)):
                return f"{round(v / spec.display_scale, 1):g} {spec.unit}".strip()
            return f"{v} {spec.unit}".strip() if spec.unit else str(v)

        return effective, {
            "key": spec.key,
            "label": spec.label,
            "requested": requested,
            "effective": effective,
            "reason": f"「{spec.label}」已从 {_fmt_val(requested)} 自动限幅为 {_fmt_val(effective)}（{'；'.join(reasons)}）",
        }
    return effective, None


@dataclass(frozen=True)
class MemoryPerformancePlan:
    """Resolved runtime performance plan (preset + sparse overrides + Anti-OOM clamping)."""

    requested_profile: str
    effective_tier: str
    hardware: HostHardwareInfo
    tier_defaults: dict[str, Any]
    overrides: dict[str, Any]
    effective_values: dict[str, Any]
    clamped_fields: tuple[dict[str, Any], ...]
    managed_by_profile: bool = False

    @property
    def sqlite_cache_size_mb(self) -> int:
        return int(self.effective_values["performance.sqlite_cache_size_mb"])

    @property
    def sqlite_cache_size_kib(self) -> int:
        return -int(self.sqlite_cache_size_mb) * 1024

    @property
    def sqlite_mmap_size_mb(self) -> int:
        return int(self.effective_values["performance.sqlite_mmap_size_mb"])

    @property
    def sqlite_mmap_size_bytes(self) -> int:
        return int(self.sqlite_mmap_size_mb) * 1024 * 1024

    @property
    def sqlite_read_pool_size(self) -> int:
        return int(self.effective_values["performance.sqlite_read_pool_size"])

    @property
    def sqlite_synchronous(self) -> str:
        val = str(self.effective_values["performance.sqlite_synchronous"]).upper()
        return val if val in {"NORMAL", "FULL"} else "NORMAL"

    @property
    def vector_precision(self) -> str:
        val = str(self.effective_values["retrieval_advanced.vector_precision"]).lower()
        return val if val in {"float32", "float16"} else "float32"

    @property
    def vector_snapshot_cache_mb(self) -> int:
        return int(self.effective_values["retrieval_advanced.vector_snapshot_cache_mb"])

    @property
    def startup_vector_warmup_enabled(self) -> bool:
        return bool(self.effective_values["retrieval_advanced.startup_vector_warmup_enabled"])

    @property
    def embedding_background_concurrency(self) -> int:
        return int(self.effective_values["retrieval_advanced.embedding_background_concurrency"])

    @property
    def hook_request_budget_seconds(self) -> float:
        return float(self.effective_values["memory_injection.hook_request_budget_seconds"])

    @property
    def recall_latency_budget_ms(self) -> int:
        return int(self.effective_values["retrieval_advanced.recall_latency_budget_ms"])

    @property
    def wal_checkpoint_min_bytes(self) -> int:
        return int(self.effective_values["maintenance.wal_checkpoint_min_bytes"])

    @property
    def background_grace_seconds(self) -> int:
        return int(self.effective_values["startup.background_grace_seconds"])

    def sqlite_pragmas(self) -> dict[str, Any]:
        return {
            "cache_size": self.sqlite_cache_size_kib,
            "temp_store": "MEMORY",
            "mmap_size": self.sqlite_mmap_size_bytes,
            "synchronous": self.sqlite_synchronous,
            "tier": self.effective_tier,
            "read_pool_size": self.sqlite_read_pool_size,
        }

    def to_api_payload(
        self,
        *,
        db_summary: dict[str, Any] | None = None,
        hot_reload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        effective_tier_spec = PERFORMANCE_TIER_BY_ID.get(self.effective_tier)
        profile_spec = PERFORMANCE_TIER_BY_ID.get(self.requested_profile)
        clamped_by_key = {item["key"]: item for item in self.clamped_fields}
        params_payload: list[dict[str, Any]] = []
        for spec in PERFORMANCE_PARAMS:
            entry = spec.to_dict()
            entry["tier_default"] = self.tier_defaults[spec.key]
            entry["effective_value"] = self.effective_values[spec.key]
            entry["overridden"] = spec.key in self.overrides
            entry["override_value"] = self.overrides.get(spec.key)
            entry["clamped"] = clamped_by_key.get(spec.key)
            params_payload.append(entry)

        payload: dict[str, Any] = {
            "profile": self.requested_profile,
            "profile_label": profile_spec.label if profile_spec else self.requested_profile,
            "effective_tier": self.effective_tier,
            "effective_tier_label": effective_tier_spec.label if effective_tier_spec else self.effective_tier,
            "override_count": len(self.overrides),
            "overrides": dict(self.overrides),
            "tier_defaults": dict(self.tier_defaults),
            "effective_values": dict(self.effective_values),
            "clamped_fields": list(self.clamped_fields),
            "hardware": self.hardware.to_dict(),
            "tiers": [spec.to_dict() for spec in PERFORMANCE_TIER_SPECS],
            "groups": list(PERFORMANCE_GROUPS),
            "params": params_payload,
            "orthogonal_notice": "功能预设（轻量 / 标准 / 陪伴）管「记多少、用哪些能力」，性能档位管「跑多快、占多少内存硬盘」，两者互不冲突。",
        }
        if db_summary is not None:
            payload["db_summary"] = db_summary
        if hot_reload is not None:
            payload["hot_reload"] = hot_reload
        return payload


def _read_config_explicit(config: ConfigView, dotted: str) -> tuple[bool, Any]:
    marker = object()
    value = config.get(dotted, marker)
    if value is marker:
        return False, None
    return True, value


def _values_equal(spec: PerformanceParamSpec, left: Any, right: Any) -> bool:
    if spec.value_type == "float":
        try:
            return abs(float(left) - float(right)) < 1e-6
        except (TypeError, ValueError):
            return False
    if spec.value_type == "int":
        try:
            return int(round(float(left))) == int(round(float(right)))
        except (TypeError, ValueError):
            return False
    if spec.value_type == "bool":
        return bool(left) is bool(right)
    return str(left).strip().lower() == str(right).strip().lower()


def resolve_performance_plan(
    config: ConfigView | dict[str, Any],
    *,
    hardware: HostHardwareInfo | None = None,
) -> MemoryPerformancePlan:
    """Resolve the active 12-parameter performance plan with Anti-OOM protection."""
    cfg = config if isinstance(config, ConfigView) else ConfigView(config)
    hw = hardware if hardware is not None else detect_host_hardware()

    raw_perf = cfg.raw.get("performance") if isinstance(cfg.raw, dict) else None
    perf_dict = raw_perf if isinstance(raw_perf, dict) else {}

    requested_profile = normalize_performance_profile(
        cfg.get("performance.profile", "auto"),
        default="auto",
    )
    effective_tier = hw.recommended_tier if requested_profile == "auto" else requested_profile
    tier_defaults = resolve_tier_defaults(effective_tier, hw)

    managed_by_profile = bool(perf_dict.get("managed_by_profile", False))
    stored_overrides = perf_dict.get("overrides") if isinstance(perf_dict.get("overrides"), dict) else {}

    overrides: dict[str, Any] = {}
    effective_values: dict[str, Any] = {}
    clamped_list: list[dict[str, Any]] = []

    for spec in PERFORMANCE_PARAMS:
        tier_val = tier_defaults[spec.key]
        raw_present, raw_val = _read_config_explicit(cfg, spec.key)
        chosen: Any = tier_val
        is_override = False

        if spec.key in SQLITE_SENTINELS:
            if raw_present and not _is_sentinel_value(spec.key, raw_val):
                try:
                    coerced = _coerce_param_value(spec, raw_val)
                    chosen = coerced
                    is_override = True
                except ValueError:
                    chosen = tier_val
        else:
            # Cross-module parameter reconciliation:
            # 1) Explicit sparse override recorded by /performance/tuning (unless edited later in module config).
            # 2) Unmanaged / upgraded config: honor values customized away from _conf_schema default.
            # 3) Managed config: honor values edited away from tier baseline in module config.
            if spec.key in stored_overrides:
                source_val = raw_val if raw_present else stored_overrides[spec.key]
                try:
                    coerced = _coerce_param_value(spec, source_val)
                    if not _values_equal(spec, coerced, tier_val):
                        chosen = coerced
                        is_override = True
                except ValueError:
                    chosen = tier_val
            elif raw_present:
                try:
                    coerced = _coerce_param_value(spec, raw_val)
                    baseline_compare = tier_val if managed_by_profile else spec.schema_default
                    if not _values_equal(spec, coerced, baseline_compare):
                        chosen = coerced
                        is_override = not _values_equal(spec, coerced, tier_val)
                except ValueError:
                    chosen = tier_val

        clamped_val, clamp_info = _clamp_param_value(spec, chosen, hw)
        effective_values[spec.key] = clamped_val
        if is_override and not _values_equal(spec, clamped_val, tier_val):
            overrides[spec.key] = clamped_val
        elif is_override and clamp_info is not None:
            # Keep user override notice visible if clamping brought it equal to tier default.
            overrides[spec.key] = clamped_val
        if clamp_info is not None:
            clamped_list.append(clamp_info)

    return MemoryPerformancePlan(
        requested_profile=requested_profile,
        effective_tier=effective_tier,
        hardware=hw,
        tier_defaults=tier_defaults,
        overrides=overrides,
        effective_values=effective_values,
        clamped_fields=tuple(clamped_list),
        managed_by_profile=managed_by_profile,
    )


def _set_nested(target: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = target
    for part in parts[:-1]:
        existing = cur.get(part)
        if not isinstance(existing, dict):
            existing = {}
            cur[part] = existing
        cur = existing
    cur[parts[-1]] = value


def build_performance_config_updates(
    raw: dict[str, Any],
    *,
    profile: str | None = None,
    overrides: dict[str, Any] | None = None,
    preserve_overrides: bool = True,
    reset_overrides: bool = False,
    hardware: HostHardwareInfo | None = None,
) -> tuple[dict[str, Any], MemoryPerformancePlan]:
    """Compute atomic config updates + resolved plan for POST /performance/tuning.

    Only the 12 whitelisted performance parameters and ``performance.*`` metadata
    are ever touched; functional presets (light/standard/companion) and protected
    security keys remain completely untouched.
    """
    hw = hardware if hardware is not None else detect_host_hardware()
    current_plan = resolve_performance_plan(raw, hardware=hw)

    if profile is not None and str(profile).strip() != "":
        norm_profile = clean_text(profile, 32).lower()
        if norm_profile not in VALID_PERFORMANCE_PROFILES:
            raise ValueError(
                f"性能档位无效：{profile!r}（可选：auto / eco / balanced / turbo / compat）"
            )
    else:
        norm_profile = current_plan.requested_profile

    effective_tier = hw.recommended_tier if norm_profile == "auto" else norm_profile
    tier_defaults = resolve_tier_defaults(effective_tier, hw)

    if reset_overrides:
        next_overrides: dict[str, Any] = {}
    elif preserve_overrides:
        next_overrides = dict(current_plan.overrides)
    else:
        next_overrides = {}

    if overrides is not None:
        if not isinstance(overrides, dict):
            raise ValueError("overrides 必须是对象（字典）")
        for key, raw_val in overrides.items():
            dotted = str(key).strip()
            spec = PERFORMANCE_PARAM_BY_KEY.get(dotted)
            if spec is None:
                raise ValueError(f"不允许通过性能调优接口修改未知或受保护配置项：{dotted}")
            if raw_val is None or (dotted in SQLITE_SENTINELS and _is_sentinel_value(dotted, raw_val)):
                next_overrides.pop(dotted, None)
                continue
            coerced = _coerce_param_value(spec, raw_val)
            next_overrides[dotted] = coerced

    updated = copy.deepcopy(dict(raw)) if isinstance(raw, dict) else {}
    perf_section = updated.get("performance")
    if not isinstance(perf_section, dict):
        perf_section = {}
        updated["performance"] = perf_section

    perf_section["profile"] = norm_profile
    perf_section["managed_by_profile"] = True

    clamped_list: list[dict[str, Any]] = []
    final_overrides: dict[str, Any] = {}
    cross_module_overrides: dict[str, Any] = {}
    effective_values: dict[str, Any] = {}

    for spec in PERFORMANCE_PARAMS:
        tier_val = tier_defaults[spec.key]
        has_override = spec.key in next_overrides
        requested = next_overrides[spec.key] if has_override else tier_val
        clamped_val, clamp_info = _clamp_param_value(spec, requested, hw)
        if clamp_info is not None:
            clamped_list.append(clamp_info)

        effective_values[spec.key] = clamped_val
        still_overridden = has_override and not _values_equal(spec, clamped_val, tier_val)

        if spec.key in SQLITE_SENTINELS:
            if still_overridden:
                perf_section[spec.field] = clamped_val
                final_overrides[spec.key] = clamped_val
            else:
                perf_section[spec.field] = SQLITE_SENTINELS[spec.key]
        else:
            _set_nested(updated, spec.key, clamped_val)
            if still_overridden:
                final_overrides[spec.key] = clamped_val
                cross_module_overrides[spec.key] = clamped_val

    perf_section["overrides"] = cross_module_overrides

    plan = MemoryPerformancePlan(
        requested_profile=norm_profile,
        effective_tier=effective_tier,
        hardware=hw,
        tier_defaults=tier_defaults,
        overrides=final_overrides,
        effective_values=effective_values,
        clamped_fields=tuple(clamped_list),
        managed_by_profile=True,
    )
    return updated, plan
