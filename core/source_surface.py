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
import re
from dataclasses import dataclass
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

#: Basis label for a surface that was stated outright in the row metadata.
BASIS_EXPLICIT = "explicit"

#: A registrable surface name: lower-case letter first, then 1-31 chars of
#: letters/digits/underscore/hyphen.  ``unknown`` and ``mixed`` describe a
#: state rather than an origin, so they are reserved and cannot be registered.
SURFACE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
RESERVED_SURFACES = frozenset({SURFACE_UNKNOWN, SURFACE_MIXED})


@dataclass(frozen=True, slots=True)
class SourceSurfaceSpec:
    """One registered surface: a name plus how a message is recognised as it."""

    name: str
    message_id_prefixes: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()


#: Registrations that ship with the plugin. A caller entry with the same name
#: is merged into it (prefixes and platforms are unioned), so a deployment can
#: widen the set without patching this module, and re-listing a built-in name
#: can never accidentally drop the ids it already had.
BUILTIN_SPECS: tuple[SourceSurfaceSpec, ...] = (
    SourceSurfaceSpec(SURFACE_MINECRAFT, (MINECRAFT_MESSAGE_PREFIX,), ()),
    SourceSurfaceSpec(SURFACE_QQ, (), tuple(sorted(QQ_PLATFORMS))),
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
    known_platforms: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Return `(surface, basis)` for one message.

    Order: message-id prefix (the bridge is authoritative for its own ids),
    then the platform family, then `unknown`. A Minecraft turn is delivered
    through the QQ adapter, so the prefix has to win over the platform.

    Prefixes are matched longest-first, so a narrower registration such as
    ``mc-raid-`` can carve ids out of the built-in ``mc-`` without changing the
    default behaviour. ``known_platforms`` maps extra platform ids onto a registered
    surface; without it the built-in QQ family is the only one.
    """
    mid = clean_token(message_id).lower()
    prefixes: dict[str, str] = {MINECRAFT_MESSAGE_PREFIX: SURFACE_MINECRAFT}
    for prefix, surface in (known_prefixes or {}).items():
        key = clean_token(prefix).lower()
        name = registered_surface_name(surface)
        if key and name:
            prefixes[key] = name
    for prefix in sorted(prefixes, key=lambda item: (-len(item), item)):
        if mid and mid.startswith(prefix):
            return prefixes[prefix], BASIS_MESSAGE_ID_PREFIX
    plat = clean_token(platform).lower()
    families = _platform_families(known_platforms)
    if plat and plat in families:
        return families[plat], BASIS_PLATFORM
    if plat:
        return SURFACE_UNKNOWN, BASIS_PLATFORM
    return SURFACE_UNKNOWN, BASIS_UNKNOWN


def source_surface_metadata(
    message_id: Any = "",
    platform: Any = "",
    *,
    known_prefixes: Mapping[str, str] | None = None,
    known_platforms: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return the metadata fragment for one message (never a `tags` value)."""
    surface, basis = detect_source_surface(
        message_id, platform, known_prefixes=known_prefixes, known_platforms=known_platforms
    )
    return {SOURCE_SURFACE_KEY: surface, SOURCE_SURFACE_BY_KEY: basis}


def merge_source_surface(
    metadata: dict[str, Any],
    message_id: Any = "",
    platform: Any = "",
    *,
    known_prefixes: Mapping[str, str] | None = None,
    known_platforms: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Merge the fragment into an existing metadata dict, caller keys win."""
    for key, value in source_surface_metadata(
        message_id,
        platform,
        known_prefixes=known_prefixes,
        known_platforms=known_platforms,
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
    known_platforms: Mapping[str, str] | None = None,
    use_platform: bool = False,
) -> str:
    """Return the surface a stored timeline/summary row carries, empty when unknown.

    Rows written before this patch have no source_surface key in their metadata;
    for those the message id prefix is used as a fallback so that summarising an
    old window still classifies what it can. Any legal registered name is kept
    as-is, so a third-party surface reads back unchanged. Pass ``use_platform=True`` only when
    the platform really identifies the surface (it does not for napcat, where QQ
    and Minecraft share one platform).
    """
    if not isinstance(row, Mapping):
        return ""
    meta = _metadata_mapping(row.get("metadata"))
    surface = normalize_surface_value(meta.get(SOURCE_SURFACE_KEY))
    if surface:
        return surface
    derived, _ = detect_source_surface(
        row.get("message_id") or meta.get("message_id", ""),
        row.get("platform", "") if use_platform else "",
        known_prefixes=known_prefixes,
        known_platforms=known_platforms,
    )
    return "" if derived == SURFACE_UNKNOWN else derived


def aggregate_source_surface(
    rows: Iterable[Mapping[str, Any]],
    *,
    known_prefixes: Mapping[str, str] | None = None,
    known_platforms: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Summarise upstream rows into the metadata fragment of a derived record.

    Rules: one distinct surface -> that surface; two or more distinct surfaces,
    or any row that is itself ``mixed`` -> ``mixed``; nothing recognised -> no keys at
    all, so derived records of pure-unknown windows keep their previous shape.
    The rule is a set of whatever the rows carry, so a registered third-party
    surface aggregates as itself instead of being folded into ``qq``.

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
        surface = row_source_surface(
            row, known_prefixes=known_prefixes, known_platforms=known_platforms
        )
        if not surface:
            continue
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
    if len(surfaces) > 1 or SURFACE_MIXED in surfaces:
        value = SURFACE_MIXED
    else:
        value = next(iter(surfaces))
    fragment: dict[str, Any] = {SOURCE_SURFACE_KEY: value}
    if refs:
        fragment[SOURCE_SURFACE_REFS_KEY] = refs
    if truncated:
        fragment[SOURCE_SURFACE_TRUNCATED_KEY] = True
    return fragment


# --------------------------------------------------------------------------
# Registration, open value domain and the weight contract
# --------------------------------------------------------------------------


def registered_surface_name(value: Any) -> str:
    """Return a registrable surface name for *value*, or '' if it cannot be one.

    Reserved states (``unknown``, ``mixed``) and anything outside
    ``SURFACE_NAME_RE`` are rejected, so configuration can never invent a label
    that collides with the aggregation rules.
    """
    token = clean_token(value).lower()
    if not token or token in RESERVED_SURFACES:
        return ""
    return token if SURFACE_NAME_RE.match(token) else ""


def normalize_surface_value(value: Any) -> str:
    """Normalise a stored surface label; '' when it is not a usable surface.

    The three legacy labels are accepted as-is, so rows written before the set
    was opened keep reading back exactly as they did. ``unknown`` maps to '' on
    purpose: callers then fall through to the prefix/platform derivation
    instead of treating "we did not know" as a surface. Any other legal token
    is kept -- the registry is a convenience, not a whitelist, because a row
    written by another plugin must stay readable if its registration is gone.
    """
    token = clean_token(value).lower()
    if not token or token == SURFACE_UNKNOWN:
        return ""
    if token in {SURFACE_MINECRAFT, SURFACE_QQ, SURFACE_MIXED}:
        return token
    return token if SURFACE_NAME_RE.match(token) else ""


def _as_list(value: Any) -> tuple[Any, ...]:
    """Accept a list/tuple or a comma-separated string as a list of entries."""
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(part for part in (piece.strip() for piece in value.split(",")) if part)
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(value)
    return (value,)


def _platform_families(known_platforms: Mapping[str, str] | None = None) -> dict[str, str]:
    """Map platform id -> surface, built-in QQ family plus caller additions."""
    families: dict[str, str] = {platform: SURFACE_QQ for platform in QQ_PLATFORMS}
    for platform, surface in (known_platforms or {}).items():
        key = clean_token(platform).lower()
        name = registered_surface_name(surface)
        if key and name:
            families[key] = name
    return families


def parse_surface_specs(raw: Any) -> tuple[SourceSurfaceSpec, ...]:
    """Parse a registry payload (JSON text or a sequence) into specs.

    Shapes accepted per entry: ``{"name": ..., "message_id_prefixes": [...],
    "platforms": [...]}``. Entries without a legal name are skipped and a
    malformed payload yields an empty tuple, so a typo in configuration can
    never take capture down -- it just leaves the built-in set in place.
    """
    entries = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return ()
        try:
            entries = json.loads(text)
        except (TypeError, ValueError):
            return ()
    if isinstance(entries, Mapping):
        entries = [entries]
    if not isinstance(entries, (list, tuple)):
        return ()
    specs: list[SourceSurfaceSpec] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        name = registered_surface_name(entry.get("name"))
        if not name:
            continue
        prefixes = tuple(
            sorted(
                {
                    clean_token(prefix).lower()
                    for prefix in _as_list(entry.get("message_id_prefixes"))
                    if clean_token(prefix)
                }
            )
        )
        platforms = tuple(
            sorted(
                {
                    clean_token(platform).lower()
                    for platform in _as_list(entry.get("platforms"))
                    if clean_token(platform)
                }
            )
        )
        specs.append(SourceSurfaceSpec(name, prefixes, platforms))
    return tuple(specs)


def surface_specs(raw: Any = None) -> tuple[SourceSurfaceSpec, ...]:
    """Built-in registrations plus caller entries (same name is merged, not replaced)."""
    parsed = parse_surface_specs(raw)
    if not parsed:
        return BUILTIN_SPECS
    merged: dict[str, SourceSurfaceSpec] = {spec.name: spec for spec in BUILTIN_SPECS}
    for spec in parsed:
        base = merged.get(spec.name)
        if base is None:
            merged[spec.name] = spec
            continue
        merged[spec.name] = SourceSurfaceSpec(
            spec.name,
            tuple(dict.fromkeys((*base.message_id_prefixes, *spec.message_id_prefixes))),
            tuple(dict.fromkeys((*base.platforms, *spec.platforms))),
        )
    return tuple(merged.values())


def source_surface_rules(raw: Any = None) -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(known_prefixes, known_platforms)`` for one registry payload.

    Callers pass the two maps straight into the detection helpers, which keeps
    this module configuration-free: it reads no config and imports no store.
    """
    prefixes: dict[str, str] = {}
    platforms: dict[str, str] = {}
    for spec in surface_specs(raw):
        for prefix in spec.message_id_prefixes:
            key = clean_token(prefix).lower()
            if key:
                prefixes[key] = spec.name
        for platform in spec.platforms:
            key = clean_token(platform).lower()
            if key:
                platforms[key] = spec.name
    return prefixes, platforms


def _clamp_weight(value: Any, *, default: float | None = 1.0) -> float | None:
    """Clamp a weight into [0, 1]; return *default* when it is not a number."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not (number == number):  # NaN
        return default
    return max(0.0, min(1.0, number))


def parse_surface_weights(raw: Any) -> dict[str, float]:
    """Parse an explicit ``{name: multiplier}`` map (JSON text or mapping).

    Unknown names, reserved states and unusable numbers are dropped, and a
    malformed payload yields an empty map: a typo degrades to "no explicit
    weights" instead of raising.
    """
    entries = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            entries = json.loads(text)
        except (TypeError, ValueError):
            return {}
    if not isinstance(entries, Mapping):
        return {}
    weights: dict[str, float] = {}
    for key, value in entries.items():
        name = normalize_surface_value(key)
        if not name or name in RESERVED_SURFACES:
            continue
        clamped = _clamp_weight(value, default=None)
        if clamped is None:
            continue
        weights[name] = clamped
    return weights


def resolve_surface_weight(
    surface: Any,
    *,
    priority: Any = "equal",
    weight: Any = 1.0,
    weights: Mapping[str, Any] | str | None = None,
    registered: Iterable[str] | None = None,
) -> float:
    """Return the score multiplier for one surface label (the weight contract).

    Precedence: an explicit ``weights`` map wins; otherwise ``priority`` names
    the primary surface and ``weight`` is applied to every other named surface.
    ``mixed``, ``unknown`` and blank labels are always 1.0 -- a mixed row carries the
    primary surface's own content, and an unknown row carries no evidence.
    When ``registered`` is supplied, a label that is not in it stays 1.0: an
    undeclared surface never opted into the priority rule, so guessing that it
    is "the other one" would discount a source nobody configured. The caller
    logs it instead of silently demoting it.

    Anything unusable falls back to 1.0 instead of raising, so this function is
    safe to call on every candidate.
    """
    name = normalize_surface_value(surface)
    if not name or name in RESERVED_SURFACES:
        return 1.0
    explicit = parse_surface_weights(weights)
    if name in explicit:
        return explicit[name]
    if registered is not None and name not in {clean_token(item).lower() for item in registered}:
        return 1.0
    chosen = clean_token(priority).lower() or "equal"
    if chosen == "equal" or chosen in RESERVED_SURFACES or chosen == name:
        return 1.0
    clamped = _clamp_weight(weight)
    return 1.0 if clamped is None else clamped
