"""Where a message came from, judged from data every adapter already has.

A Minecraft chat bridge plugin injects in-game chat into the normal AstrBot
pipeline and gives every such turn a message id of `mc-<turn_id>`. QQ
traffic arrives through napcat/aiocqhttp and keeps the platform message id.

Both surfaces share one persona and one conversation bucket on purpose, so the
`platform` column alone cannot tell them apart: an MC turn is stored under the
same `napcat:FriendMessage:<qq>` session as the QQ chat with that person. This
module derives a small stable label from the message id first and the platform
second, and hands back the metadata keys the memory writers merge into their
records. It is pure: no database, no network, no configuration reads.

The label lives in `metadata` only. It is deliberately *not* written to
`tags`: tags feed the FTS text (the store indexes `" ".join(tags)`), so a tag
here would pollute keyword recall for every row.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

SOURCE_SURFACE_KEY = "source_surface"
SOURCE_SURFACE_BY_KEY = "source_surface_by"
SOURCE_SURFACE_REFS_KEY = "source_surface_refs"
SOURCE_SURFACE_TRUNCATED_KEY = "source_surface_truncated"

SURFACE_MINECRAFT = "minecraft"
SURFACE_QQ = "qq"
SURFACE_MIXED = "mixed"
SURFACE_UNKNOWN = "unknown"

BASIS_MESSAGE_ID_PREFIX = "message_id_prefix"
BASIS_PLATFORM = "platform"
BASIS_UNKNOWN = "unknown"

#: Message ids created by the Minecraft bridge plugin start with this prefix.
MINECRAFT_MESSAGE_PREFIX = "mc-"

#: Upper bound on how many upstream row ids a derived record keeps.
MAX_AGGREGATED_REFS = 32

#: Platform ids that are OneBot/QQ bridges. Listed in one place so the label
#: does not depend on which of them a deployment happens to use.
QQ_PLATFORMS = frozenset(
    {
        "napcat",
        "aiocqhttp",
        "qq",
        "onebot",
        "onebot_qq",
        "onebot11",
        "go-cqhttp",
        "cqhttp",
        "qqofficial",
        "qq_official",
        "qqbot",
    }
)


def clean_token(value: Any) -> str:
    """Trim a value into a comparable token; anything unusable becomes ''."""
    if value is None:
        return ""
    try:
        text = str(value)
    except Exception:
        return ""
    return text.strip()


def detect_source_surface(
    message_id: Any = "",
    platform: Any = "",
    *,
    known_prefixes: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Return `(surface, basis)` for one message.

    Order: message-id prefix (the bridge is authoritative for its own ids),
    then the platform family, then `unknown`. A Minecraft turn is delivered
    through the QQ adapter, so the prefix has to win over the platform.
    """
    mid = clean_token(message_id).lower()
    prefixes: dict[str, str] = {MINECRAFT_MESSAGE_PREFIX: SURFACE_MINECRAFT}
    if known_prefixes:
        for prefix, surface in known_prefixes.items():
            key = clean_token(prefix).lower()
            if key:
                prefixes[key] = clean_token(surface).lower() or SURFACE_UNKNOWN
    for prefix, surface in prefixes.items():
        if mid.startswith(prefix):
            return surface, BASIS_MESSAGE_ID_PREFIX
    plat = clean_token(platform).lower()
    if plat in QQ_PLATFORMS:
        return SURFACE_QQ, BASIS_PLATFORM
    if plat:
        return SURFACE_UNKNOWN, BASIS_PLATFORM
    return SURFACE_UNKNOWN, BASIS_UNKNOWN


def source_surface_metadata(
    message_id: Any = "",
    platform: Any = "",
    *,
    known_prefixes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return the metadata fragment for one message (never a `tags` value)."""
    surface, basis = detect_source_surface(message_id, platform, known_prefixes=known_prefixes)
    return {SOURCE_SURFACE_KEY: surface, SOURCE_SURFACE_BY_KEY: basis}


def merge_source_surface(
    metadata: dict[str, Any],
    message_id: Any = "",
    platform: Any = "",
    *,
    known_prefixes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Merge the fragment into an existing metadata dict, caller keys win."""
    for key, value in source_surface_metadata(
        message_id, platform, known_prefixes=known_prefixes
    ).items():
        metadata.setdefault(key, value)
    return metadata


def _metadata_mapping(value: Any) -> dict[str, Any]:
    """Coerce a timeline row metadata column (JSON text or dict) to a dict."""
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def row_source_surface(
    row: Mapping[str, Any],
    *,
    known_prefixes: Mapping[str, str] | None = None,
    use_platform: bool = False,
) -> str:
    """Return the surface a stored timeline/summary row carries, empty when unknown.

    Rows written before this patch have no source_surface key in their metadata;
    for those the message id prefix is used as a fallback so that summarising an
    old window still classifies what it can. Pass ``use_platform=True`` only when
    the platform really identifies the surface (it does not for napcat, where QQ
    and Minecraft share one platform).
    """
    if not isinstance(row, Mapping):
        return ""
    meta = _metadata_mapping(row.get("metadata"))
    surface = clean_token(meta.get(SOURCE_SURFACE_KEY)).lower()
    if surface in {SURFACE_MINECRAFT, SURFACE_QQ, SURFACE_MIXED}:
        return surface
    derived, _ = detect_source_surface(
        row.get("message_id") or meta.get("message_id", ""),
        row.get("platform", "") if use_platform else "",
        known_prefixes=known_prefixes,
    )
    return "" if derived == SURFACE_UNKNOWN else derived


def aggregate_source_surface(
    rows: Iterable[Mapping[str, Any]],
    *,
    known_prefixes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Summarise upstream rows into the metadata fragment of a derived record.

    Rules: minecraft only -> minecraft; qq only -> qq; both -> mixed; nothing
    recognised -> no keys at all, so derived records of pure-unknown windows keep
    their previous shape.

    The ``platform`` column is deliberately *not* used here: QQ and Minecraft share
    the napcat platform, so inferring from it would relabel exactly the rows this
    patch exists to separate. Only an explicit ``source_surface`` in the row
    metadata or the ``mc-`` message id prefix counts.
    """
    surfaces: set[str] = set()
    refs: list[str] = []
    seen: set[str] = set()
    truncated = False
    for row in rows or ():
        surface = row_source_surface(row, known_prefixes=known_prefixes)
        if not surface:
            continue
        if surface == SURFACE_MIXED:
            surfaces.update({SURFACE_MINECRAFT, SURFACE_QQ})
        else:
            surfaces.add(surface)
        ref = clean_token(row.get("id")) if isinstance(row, Mapping) else ""
        if not ref or ref in seen:
            continue
        seen.add(ref)
        if len(refs) >= MAX_AGGREGATED_REFS:
            truncated = True
            continue
        refs.append(ref)
    if not surfaces:
        return {}
    if SURFACE_MINECRAFT in surfaces and SURFACE_QQ in surfaces:
        value = SURFACE_MIXED
    elif SURFACE_MINECRAFT in surfaces:
        value = SURFACE_MINECRAFT
    else:
        value = SURFACE_QQ
    fragment: dict[str, Any] = {SOURCE_SURFACE_KEY: value}
    if refs:
        fragment[SOURCE_SURFACE_REFS_KEY] = refs
    if truncated:
        fragment[SOURCE_SURFACE_TRUNCATED_KEY] = True
    return fragment
