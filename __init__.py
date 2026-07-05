try:
    from .main import MemoryCompanionPlugin
except ModuleNotFoundError as exc:
    if exc.name != "astrbot":
        raise
    MemoryCompanionPlugin = None

__all__ = ["MemoryCompanionPlugin"]
