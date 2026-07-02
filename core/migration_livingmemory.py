from __future__ import annotations

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import EntityRef, MemoryRecord, clean_text, new_id
from .store import MemoryStore


CONTENT_COLUMNS = ("text", "content", "summary", "memory", "canonical_summary", "persona_summary", "page_content")
SESSION_COLUMNS = ("session_id", "session", "origin", "unified_msg_origin")
PERSONA_COLUMNS = ("persona_id", "persona", "bot_id")
TIME_COLUMNS = ("created_at", "updated_at", "timestamp", "time", "last_accessed")
IMPORT_TABLE_PRIORITY = {
    "documents": 0,
}
DERIVED_TABLES = {"memory_atoms", "graph_entries", "messages"}
SKIP_TABLES = {
    "db_version",
    "migration_status",
    "memory_write_ops",
    "graph_edges",
    "graph_nodes",
    "graph_entry_nodes",
}


class LivingMemoryMigrator:
    def __init__(self, store: MemoryStore, plugin_root: Path, data_dir: Path):
        self.store = store
        self.plugin_root = Path(plugin_root)
        self.data_dir = Path(data_dir)

    def candidate_paths(self, configured_path: str = "") -> list[Path]:
        candidates: list[Path] = []
        if configured_path:
            candidates.append(Path(configured_path).expanduser())

        plugins_dir = self.plugin_root.parent
        data_parent = self.data_dir.parent
        candidates.extend(
            [
                plugins_dir / "astrbot_plugin_livingmemory" / "data" / "livingmemory.db",
                plugins_dir / "astrbot_plugin_livingmemory" / "livingmemory.db",
                data_parent / "astrbot_plugin_livingmemory" / "livingmemory.db",
                data_parent / "astrbot_plugin_livingmemory" / "memory.db",
                data_parent / "livingmemory.db",
            ]
        )

        for base in [plugins_dir / "astrbot_plugin_livingmemory", data_parent / "astrbot_plugin_livingmemory"]:
            if base.exists():
                candidates.extend(base.rglob("*.db"))

        unique: list[Path] = []
        seen: set[str] = set()
        for path in candidates:
            try:
                key = str(path.resolve())
            except Exception:
                key = str(path)
            if key not in seen:
                seen.add(key)
                unique.append(path)
        return unique

    def preview(self, configured_path: str = "") -> dict[str, Any]:
        paths = self.candidate_paths(configured_path)
        reports = []
        for path in paths:
            if not path.exists() or not path.is_file():
                continue
            report = self._inspect_db(path)
            if report:
                reports.append(report)
        return {"candidates": reports, "count": len(reports)}

    async def import_data(
        self,
        *,
        configured_path: str = "",
        default_review_status: str = "auto",
        limit: int = 5000,
    ) -> dict[str, Any]:
        preview = self.preview(configured_path)
        if not preview["candidates"]:
            return {"imported": 0, "skipped": 0, "reason": "未找到可用 LivingMemory 数据库"}

        source = preview["candidates"][0]
        path = Path(source["path"])
        batch_id = await self.store.add_import_batch(
            source_plugin="livingmemory",
            source_path=str(path),
            mode="import",
            stats={"tables": source.get("tables", [])},
        )
        imported = 0
        skipped = 0
        importable_tables: list[dict[str, Any]] = []
        skipped_tables: list[dict[str, Any]] = []
        for table in source.get("tables", []):
            if not table.get("importable"):
                skipped_tables.append(
                    {
                        "name": table.get("name"),
                        "count": table.get("count", 0),
                        "note": table.get("note") or "not_importable",
                    }
                )
                continue
            before_table = imported
            remaining = max(0, limit - imported) if limit > 0 else int(table.get("count") or 0)
            rows = self._read_rows(path, table["name"], table["columns"], limit=remaining)
            for row in rows:
                record = self._row_to_record(row, table["columns"], table["name"], batch_id, default_review_status)
                if not record:
                    skipped += 1
                    continue
                await self.store.insert_memory(record)
                imported += 1
                if limit > 0 and imported >= limit:
                    break
            if limit > 0 and imported >= limit:
                importable_tables.append(
                    {
                        "name": table.get("name"),
                        "count": table.get("count", 0),
                        "imported": imported - before_table,
                    }
                )
                break
            importable_tables.append(
                {
                    "name": table.get("name"),
                    "count": table.get("count", 0),
                    "imported": imported - before_table,
                }
            )
        return {
            "imported": imported,
            "skipped": skipped,
            "batch_id": batch_id,
            "source_path": str(path),
            "strategy": "只导入 documents 完整摘要，跳过 graph_entries/memory_atoms/messages 等派生碎片。",
            "default_review_status": default_review_status,
            "import_limit": limit,
            "importable_tables": importable_tables,
            "skipped_tables": skipped_tables,
        }

    async def repair_imported_content(self, configured_path: str = "") -> dict[str, Any]:
        preview = self.preview(configured_path)
        if not preview["candidates"]:
            return {"updated": 0, "skipped": 0, "reason": "未找到可用 LivingMemory 数据库"}
        path = Path(preview["candidates"][0]["path"])
        candidates = await self.store.list_livingmemory_content_repair_candidates()
        if not candidates:
            return {"updated": 0, "skipped": 0, "source_path": str(path)}

        updated = 0
        skipped = 0
        try:
            conn = sqlite3.connect(str(path))
            conn.row_factory = sqlite3.Row
            for item in candidates:
                payload = self._repair_payload(conn, item)
                if not payload:
                    skipped += 1
                    continue
                if await self.store.update_livingmemory_import_payload(item["id"], payload):
                    updated += 1
                else:
                    skipped += 1
            conn.close()
        except Exception as exc:
            return {"updated": updated, "skipped": skipped, "source_path": str(path), "error": str(exc)}
        return {"updated": updated, "skipped": skipped, "source_path": str(path)}

    def _inspect_db(self, path: Path) -> dict[str, Any] | None:
        try:
            conn = sqlite3.connect(str(path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            tables = []
            for row in rows:
                table = row["name"]
                table_key = table.lower()
                if table.startswith("sqlite_") or "_fts" in table_key or table_key in SKIP_TABLES:
                    continue
                columns = [item["name"] for item in conn.execute(f"PRAGMA table_info({self._quote(table)})").fetchall()]
                count = conn.execute(f"SELECT COUNT(*) FROM {self._quote(table)}").fetchone()[0]
                content_col = self._pick_content_column(columns)
                is_derived = table_key in DERIVED_TABLES
                tables.append(
                    {
                        "name": table,
                        "columns": columns,
                        "count": count,
                        "content_column": content_col,
                        "session_column": self._pick_exact(columns, SESSION_COLUMNS),
                        "persona_column": self._pick(columns, PERSONA_COLUMNS),
                        "time_column": self._pick_exact(columns, TIME_COLUMNS),
                        "importable": bool(content_col and count > 0 and not is_derived),
                        "note": "derived_fragment_not_imported" if is_derived else "",
                    }
                )
            conn.close()
            if not tables:
                return None
            tables.sort(key=lambda item: (IMPORT_TABLE_PRIORITY.get(str(item.get("name") or "").lower(), 50), str(item.get("name") or "")))
            return {"path": str(path), "tables": tables}
        except Exception as exc:
            return {"path": str(path), "error": str(exc), "tables": []}

    def _read_rows(self, path: Path, table: str, columns: list[str], limit: int) -> list[sqlite3.Row]:
        if limit <= 0:
            return []
        try:
            conn = sqlite3.connect(str(path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(f"SELECT * FROM {self._quote(table)} LIMIT ?", (limit,)).fetchall()
            conn.close()
            return rows
        except Exception:
            return []

    def _row_to_record(
        self,
        row: sqlite3.Row,
        columns: list[str],
        table_name: str,
        batch_id: str,
        default_review_status: str,
    ) -> MemoryRecord | None:
        table_key = table_name.lower()
        if table_key in SKIP_TABLES:
            return None
        if table_key == "memory_atoms":
            status = clean_text(self._row_get(row, "status"), 40).lower()
            if status in {"expired", "deleted", "archived", "disabled"}:
                return None

        content_col = self._pick_content_column(columns)
        if not content_col:
            return None
        content = clean_text(row[content_col], 3000)
        if not content:
            return None

        source_metadata = self._loads(self._row_get(row, "metadata"), {})
        if not isinstance(source_metadata, dict):
            source_metadata = {}
        session_col = self._pick_exact(columns, SESSION_COLUMNS)
        session_id = clean_text(row[session_col], 200) if session_col else ""
        session_id = clean_text(session_id or source_metadata.get("session_id"), 200)
        scope, target = self._scope_from_session(session_id)
        group_id = target if scope == "group" else ""
        object_ref = EntityRef(kind="group" if scope == "group" else "user", id=target, role="imported_target")
        visibility = "group_public" if scope == "group" else ("private_pair" if scope == "private" else "internal")
        occurred_col = self._pick_exact(columns, TIME_COLUMNS)
        occurred_at = self._normalize_time(row[occurred_col]) if occurred_col else ""

        memory_type = self._memory_type_for_table(table_key, row)
        importance = self._float(self._row_get(row, "importance"), self._float(source_metadata.get("importance"), 0.35))
        confidence = self._float(self._row_get(row, "confidence"), self._float(source_metadata.get("confidence"), 0.55))
        tags = ["livingmemory_import", table_name]
        atom_type = clean_text(self._row_get(row, "atom_type"), 60)
        if atom_type:
            tags.append(atom_type)
        entry_type = clean_text(self._row_get(row, "entry_type"), 60)
        if entry_type:
            tags.append(entry_type)
        status = clean_text(self._row_get(row, "status"), 60)
        if status:
            tags.append(f"status:{status}")
        metadata = {
            "source_table": table_name,
            "source_row_id": self._row_get(row, "id"),
            "source_doc_id": self._row_get(row, "doc_id"),
            "source_memory_id": self._row_get(row, "source_memory_id") or self._row_get(row, "parent_memory_id"),
            "persona_id": clean_text(self._row_get(row, "persona_id") or source_metadata.get("persona_id"), 120),
            "livingmemory_metadata": source_metadata,
        }
        metadata.update(self._promoted_metadata(source_metadata))
        metadata = {key: value for key, value in metadata.items() if value not in ("", None, {}, [])}

        return MemoryRecord(
            id=new_id("imported"),
            memory_type=memory_type,
            subject=EntityRef(kind="unknown", id="", role="imported_subject"),
            object=object_ref,
            scope=scope,
            session_id=session_id,
            platform=session_id.split(":", 1)[0] if ":" in session_id else "",
            group_id=group_id,
            visibility=visibility,
            sayability="indirect",
            reality_level="imported_summary",
            lifecycle="stable_memory",
            content=content,
            evidence=content,
            confidence=confidence,
            importance=importance,
            review_status=default_review_status if default_review_status in {"pending", "auto"} else "auto",
            tags=tags,
            metadata=metadata,
            occurred_at=occurred_at,
            source_plugin="livingmemory",
            import_batch_id=batch_id,
        )

    def _memory_type_for_table(self, table_name: str, row: sqlite3.Row) -> str:
        if table_name == "memory_atoms":
            atom_type = clean_text(self._row_get(row, "atom_type"), 60)
            return f"livingmemory_atom:{atom_type}" if atom_type else "livingmemory_atom"
        if table_name == "graph_entries":
            entry_type = clean_text(self._row_get(row, "entry_type"), 60)
            return f"livingmemory_graph:{entry_type}" if entry_type else "livingmemory_graph"
        if table_name == "documents":
            return "conversation_summary"
        if table_name == "messages":
            return "conversation_event"
        return "imported_memory"

    def _promoted_metadata(self, source_metadata: dict[str, Any]) -> dict[str, Any]:
        promoted: dict[str, Any] = {}
        for key in ("canonical_summary", "persona_summary", "sentiment", "interaction_type", "summary_quality"):
            value = clean_text(source_metadata.get(key), 1200 if key.endswith("summary") else 80)
            if value:
                promoted[key] = value
        for key, limit, item_limit in (
            ("topics", 8, 80),
            ("key_facts", 10, 180),
            ("participants", 12, 80),
        ):
            value = source_metadata.get(key)
            if isinstance(value, list):
                items = [clean_text(item, item_limit) for item in value if clean_text(item, item_limit)]
                if items:
                    promoted[key] = items[:limit]
        source_window = source_metadata.get("source_window")
        if isinstance(source_window, dict):
            promoted["source_window"] = source_window
        return promoted

    def _pick(self, columns: list[str], names: tuple[str, ...]) -> str:
        return self._pick_exact(columns, names)

    def _pick_exact(self, columns: list[str], names: tuple[str, ...]) -> str:
        lowered = {column.lower(): column for column in columns}
        for name in names:
            if name in lowered:
                return lowered[name]
        return ""

    def _pick_content_column(self, columns: list[str]) -> str:
        exact = self._pick_exact(columns, CONTENT_COLUMNS)
        if exact:
            return exact
        safe_tokens = {"summary", "memory", "text", "content"}
        for column in columns:
            lower = column.lower()
            if lower in {"id", "doc_id", "edge_key", "node_key", "metadata", "status", "memory_id", "parent_memory_id", "source_memory_id"}:
                continue
            if any(token in lower for token in safe_tokens):
                return column
        return ""

    def _repair_payload(self, conn: sqlite3.Connection, item: dict[str, Any]) -> dict[str, Any] | None:
        metadata = self._loads(item.get("metadata"), {})
        source_table = clean_text(metadata.get("source_table"), 80)
        source_row_id = self._int(item.get("content"))
        if not source_table or source_row_id <= 0:
            return None

        if source_table == "graph_edges":
            row = conn.execute("SELECT * FROM graph_edges WHERE id=?", (source_row_id,)).fetchone()
            if not row:
                return self._document_repair_payload(conn, source_row_id, metadata)
            edge_meta = self._loads(row["metadata"], {})
            text = clean_text(edge_meta.get("summary"), 4000)
            if not text:
                return None
            doc_meta: dict[str, Any] = {}
            doc_row = None
            if row["source_memory_id"]:
                doc_row = conn.execute("SELECT * FROM documents WHERE id=?", (row["source_memory_id"],)).fetchone()
                if doc_row:
                    doc_meta = self._loads(doc_row["metadata"], {})
            session_id = clean_text(doc_meta.get("session_id"), 200)
            scope, target = self._scope_from_session(session_id)
            group_id = target if scope == "group" else ""
            metadata.update(
                {
                    "source_table": source_table,
                    "source_row_id": source_row_id,
                    "source_memory_id": row["source_memory_id"],
                    "source_relation_type": row["relation_type"],
                    "source_edge_key": row["edge_key"],
                    "repaired_from_numeric_content": True,
                }
            )
            return {
                "content": text,
                "evidence": text,
                "metadata": metadata,
                "scope": scope,
                "session_id": session_id,
                "group_id": group_id,
                "visibility": "group_public" if scope == "group" else ("private_pair" if scope == "private" else "internal"),
                "object_kind": "group" if scope == "group" else "user",
                "object_id": target,
                "object_role": "imported_target",
                "occurred_at": clean_text((doc_row["created_at"] if doc_row else "") or row["created_at"], 80),
            }

        if source_table == "documents":
            return self._document_repair_payload(conn, source_row_id, metadata)
        return None

    def _document_repair_payload(
        self,
        conn: sqlite3.Connection,
        source_row_id: int,
        metadata: dict[str, Any],
    ) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM documents WHERE id=?", (source_row_id,)).fetchone()
        if not row:
            return None
        text = clean_text(row["text"], 4000)
        if not text:
            return None
        doc_meta = self._loads(row["metadata"], {})
        session_id = clean_text(doc_meta.get("session_id"), 200)
        scope, target = self._scope_from_session(session_id)
        group_id = target if scope == "group" else ""
        metadata.update(
            {
                "source_table": "documents",
                "source_row_id": source_row_id,
                "source_doc_id": row["doc_id"],
                "repaired_from_numeric_content": True,
            }
        )
        return {
            "content": text,
            "evidence": text,
            "metadata": metadata,
            "scope": scope,
            "session_id": session_id,
            "group_id": group_id,
            "visibility": "group_public" if scope == "group" else ("private_pair" if scope == "private" else "internal"),
            "object_kind": "group" if scope == "group" else "user",
            "object_id": target,
            "object_role": "imported_target",
            "occurred_at": clean_text(row["created_at"], 80),
        }

    def _loads(self, value: Any, fallback: Any) -> Any:
        if isinstance(value, dict):
            return value
        try:
            return json.loads(value or "")
        except Exception:
            return fallback

    def _int(self, value: Any) -> int:
        try:
            return int(str(value).strip())
        except Exception:
            return 0

    def _float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _row_get(self, row: sqlite3.Row, key: str, default: Any = "") -> Any:
        try:
            if key in row.keys():
                return row[key]
        except Exception:
            pass
        return default

    def _normalize_time(self, value: Any) -> str:
        if value in (None, ""):
            return ""
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
            except Exception:
                return clean_text(value, 80)
        text = clean_text(value, 80)
        try:
            numeric = float(text)
            if numeric > 1000000000:
                return datetime.fromtimestamp(numeric, tz=timezone.utc).isoformat()
        except Exception:
            pass
        return text

    def _scope_from_session(self, session_id: str) -> tuple[str, str]:
        if ":GroupMessage:" in session_id:
            return "group", session_id.rsplit(":GroupMessage:", 1)[-1]
        if ":FriendMessage:" in session_id:
            return "private", session_id.rsplit(":FriendMessage:", 1)[-1]
        if ":PrivateMessage:" in session_id:
            return "private", session_id.rsplit(":PrivateMessage:", 1)[-1]
        return "unknown", ""

    def _quote(self, name: str) -> str:
        return '"' + name.replace('"', '""') + '"'
