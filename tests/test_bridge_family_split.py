from __future__ import annotations

import ast
import asyncio
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from core import bridge
from core.bridge_external_record import ExternalRecordBridgeFamily
from core.bridge_maintenance import MaintenanceBridgeFamily
from core.bridge_portrait_emotion import PortraitEmotionBridgeFamily
from core.bridge_producer import ProducerBridgeFamily
from core.bridge_recall import RecallBridgeFamily
from core.bridge_scoped_namespace import ScopedNamespaceBridgeFamily


ROOT = Path(__file__).resolve().parents[1]

FAMILY_METHODS = {'recall': ('read_bot_personal_profile',
            'search_bot_personal_profile',
            'read_bot_profile',
            'read_profile',
            'search',
            'compose_injection',
            'compose_context',
            'remember',
            'recall',
            'get_token_usage_summary',
            'should_defer_private_companion_section',
            'mark_visibility',
            'search_open_loops'),
 'external_record': ('record_event',
                     'record_external_memory',
                     'record_bot_action',
                     'record_persona_life',
                     'record_proactive_message',
                     'record_visible_turn',
                     'record_shared_experience',
                     'record_search_action',
                     'record_creative_work',
                     'record_image_action',
                     'record_qzone_action',
                     'record_reading',
                     'record_schedule_fragment',
                     'record_bot_personal_archive',
                     'record_bot_personal_memory'),
 'scoped_namespace': ('consume_person_projection',
                      'consume_context_projection',
                      'probe_namespace_context_capabilities',
                      'bind_namespace_migration_epoch',
                      'upsert_scoped_record',
                      'read_scoped_record',
                      'list_scoped_records',
                      'tombstone_scoped_record',
                      'tombstone_scoped_namespace',
                      'tombstone_scoped_identity_scopes',
                      'erase_scoped_group_scopes',
                      'erase_scoped_persona_scopes'),
 'portrait_emotion': ('consume_relationship_projection',
                      'consume_expression_decision',
                      'read_user_memory_summary',
                      'read_unified_profile_portrait',
                      'unified_profile_portrait_status',
                      'run_unified_profile_portrait_batch',
                      'get_emotional_events',
                      'list_emotion_events',
                      'ack_emotion_events',
                      'record_emotion_event',
                      'revise_emotion_event',
                      'get_emotion_trace',
                      'get_emotion_trace_diagnostic',
                      'get_emotion_trace_summary',
                      'get_relationship_phase',
                      'peek_relationship_phase',
                      'get_recent_emotional_state'),
 'producer': ('register_emotion_producer',
              'register_private_companion',
              'register_bot_personal_producer',
              'register_external_memory_producer',
              'create_external_memory_context',
              'create_emotion_producer_context',
              'create_emotion_delivery_context',
              'bind_emotion_page_api',
              'create_emotion_admin_context',
              'create_user_memory_context',
              'probe_capability_snapshot',
              'probe_bot_personal_memory_capabilities',
              'capability_status',
              'mark_capability_negative'),
 'maintenance': ('bridge_lifecycle_status',
                 'deactivate',
                 'p5_capability_status',
                 'provenance_snapshot',
                 'provenance_preview',
                 'provenance_apply',
                 'provenance_backup',
                 'provenance_rollback',
                 'create_note',
                 'read_notes',
                 'delete_note',
                 'coordination_status',
                 'create_cross_window_thread')}

PUBLIC_API = {'bridge_lifecycle_status': ("(self) -> 'dict[str, Any]'", False, 'maintenance'),
 'deactivate': ("(self) -> 'None'", False, 'maintenance'),
 'register_emotion_producer': ("(self, producer: 'Any') -> 'Any | None'", False, 'producer'),
 'register_private_companion': ("(self, producer: 'Any') -> 'Any | None'", False, 'producer'),
 'register_bot_personal_producer': ("(self, producer: 'Any') -> 'Any | None'", False, 'producer'),
 'register_external_memory_producer': ("(self, producer: 'Any') -> 'Any | None'", False, 'producer'),
 'create_external_memory_context': ("(self, capability: 'Any', *, user_id: 'str') -> 'Any | None'", False, 'producer'),
 'create_emotion_producer_context': ("(self, capability: 'Any', *, bot_id: 'str', scope: 'str', platform: 'str', user_id: 'str', session_id: 'str') -> 'Any | "
                                     "None'",
                                     False,
                                     'producer'),
 'create_emotion_delivery_context': ("(self, capability: 'Any', *, bot_id: 'str', scope: 'str', platform: 'str', user_id: 'str', session_id: 'str', "
                                     "consumer_id: 'str' = 'private_companion.daily_state', allow_cross_window: 'bool' = False) -> 'Any | None'",
                                     False,
                                     'producer'),
 'bind_emotion_page_api': ("(self, page_api: 'Any') -> 'Any | None'", False, 'producer'),
 'create_emotion_admin_context': ("(self, capability: 'Any', *, bot_id: 'str', scope: 'str', session_id: 'str') -> 'Any | None'", False, 'producer'),
 'consume_relationship_projection': ("(self, projection: 'Any', *, producer_capability: 'Any' = None, producer_context: 'Any' = None, bot_id: 'str' = '', "
                                     "platform: 'str' = '', user_id: 'str' = '', scope: 'str' = 'private', session_id: 'str' = '') -> 'dict[str, Any]'",
                                     False,
                                     'portrait_emotion'),
 'consume_expression_decision': ("(self, decision: 'Any', *, producer_capability: 'Any' = None, producer_context: 'Any' = None, bot_id: 'str' = '', platform: "
                                 "'str' = '', user_id: 'str' = '', scope: 'str' = 'private', session_id: 'str' = '') -> 'dict[str, Any]'",
                                 False,
                                 'portrait_emotion'),
 'create_user_memory_context': ("(self, capability: 'Any', **kwargs: 'Any') -> 'Any | None'", False, 'producer'),
 'record_event': ("(self, *, content: 'str', memory_type: 'str' = 'external_event', scope: 'str' = 'unknown', session_id: 'str' = '', platform: 'str' = '', "
                  "message_id: 'str' = '', group_id: 'str' = '', subject: 'dict[str, Any] | None' = None, object: 'dict[str, Any] | None' = None, visibility: "
                  "'str' = 'bot_self', sayability: 'str' = 'direct', reality_level: 'str' = 'bot_action', lifecycle: 'str' = 'stable_memory', confidence: "
                  "'float' = 0.85, importance: 'float' = 0.5, review_status: 'str' = 'auto', tags: 'list[str] | None' = None, metadata: 'dict[str, Any] | "
                  "None' = None, source_plugin: 'str' = 'external', memory_id: 'str' = '', occurred_at: 'str' = '') -> 'str'",
                  True,
                  'external_record'),
 'record_external_memory': ("(self, *, user_id: 'str' = '', content: 'str' = '', summary: 'str' = '', payload: 'dict[str, Any] | None' = None, memory_type: "
                            "'str' = 'external_memory', source_plugin: 'str' = 'external', occurred_at: 'str' = '', idempotency_key: 'str' = '', memory_id: "
                            "'str' = '', importance: 'float' = 0.62, confidence: 'float' = 0.82, tags: 'list[str] | None' = None, metadata: 'dict[str, Any] | "
                            "None' = None, long_term: 'bool' = True, producer_capability: 'Any' = None, producer_context: 'Any' = None) -> 'dict[str, Any]'",
                            True,
                            'external_record'),
 'record_bot_action': ("(self, *, content: 'str', **kwargs: 'Any') -> 'str'", True, 'external_record'),
 'record_persona_life': ("(self, *, content: 'str', **kwargs: 'Any') -> 'str'", True, 'external_record'),
 'record_proactive_message': ("(self, *, content: 'str', **kwargs: 'Any') -> 'str'", True, 'external_record'),
 'record_visible_turn': ("(self, *, role: 'str', content: 'str', **kwargs: 'Any') -> 'str'", True, 'external_record'),
 'record_shared_experience': ("(self, *, content: 'str', experience_type: 'str', bot_id: 'str' = '', bot_name: 'str' = '', user_id: 'str' = '', user_name: "
                              "'str' = '', scope: 'str' = 'private', session_id: 'str' = '', platform: 'str' = '', source_plugin: 'str' = 'external', "
                              "memory_id: 'str' = '', confidence: 'float' = 0.9, importance: 'float' = 0.7, metadata: 'dict[str, Any] | None' = None) -> 'str'",
                              True,
                              'external_record'),
 'record_search_action': ("(self, *, content: 'str', **kwargs: 'Any') -> 'str'", True, 'external_record'),
 'record_creative_work': ("(self, *, content: 'str', **kwargs: 'Any') -> 'str'", True, 'external_record'),
 'record_image_action': ("(self, *, content: 'str', **kwargs: 'Any') -> 'str'", True, 'external_record'),
 'record_qzone_action': ("(self, *, content: 'str', **kwargs: 'Any') -> 'str'", True, 'external_record'),
 'record_reading': ("(self, *, content: 'str', **kwargs: 'Any') -> 'str'", True, 'external_record'),
 'record_schedule_fragment': ("(self, *, content: 'str', **kwargs: 'Any') -> 'str'", True, 'external_record'),
 'record_bot_personal_archive': ("(self, envelope: 'BotPersonalArchiveDTO | dict[str, Any]', *, producer_capability: 'Any' = None, producer_context: 'Any' = "
                                 "None) -> 'dict[str, Any]'",
                                 True,
                                 'external_record'),
 'record_bot_personal_memory': ("(self, *, memory_type: 'str', payload: 'dict[str, Any] | None' = None, producer_capability: 'Any' = None, producer_context: "
                                "'Any' = None, **kwargs: 'Any') -> 'dict[str, Any]'",
                                True,
                                'external_record'),
 'read_bot_personal_profile': ("(self, query: 'str' = '', *, limit: 'int' = 10, producer_capability: 'Any' = None) -> 'dict[str, Any]'", True, 'recall'),
 'read_user_memory_summary': ("(self, user_id: 'str', *, session_id: 'str' = '', limit: 'int' = 6, requester_context: 'Any' = None) -> 'dict[str, Any]'",
                              True,
                              'portrait_emotion'),
 'read_unified_profile_portrait': ("(self, request: 'dict[str, Any]', *, limit: 'int' = 8) -> 'dict[str, Any]'", True, 'portrait_emotion'),
 'unified_profile_portrait_status': ("(self, person_id: 'str') -> 'dict[str, Any]'", True, 'portrait_emotion'),
 'run_unified_profile_portrait_batch': ("(self, person_id: 'str', *, run_day: 'str' = '') -> 'dict[str, Any]'", True, 'portrait_emotion'),
 'search_bot_personal_profile': ("(self, query: 'str' = '', *, limit: 'int' = 10, producer_capability: 'Any' = None) -> 'dict[str, Any]'", True, 'recall'),
 'read_bot_profile': ("(self, profile: 'str', query: 'str' = '', *, limit: 'int' = 10, current_date: 'str' = '', current_window: 'str' = '', authorized: "
                      "'bool' = False, producer_capability: 'Any' = None, producer_context: 'Any' = None) -> 'dict[str, Any]'",
                      True,
                      'recall'),
 'read_profile': ("(self, profile: 'str', query: 'str' = '', **kwargs: 'Any') -> 'dict[str, Any]'", True, 'recall'),
 'search': ("(self, query: 'str', *, session_context: 'SessionContext | dict[str, Any] | None' = None, top_k: 'int | None' = None, p5_attestation: 'Any' = "
            "None, p5_attestation_consumer: 'Any' = None) -> 'list[dict[str, Any]]'",
            True,
            'recall'),
 'compose_injection': ("(self, query: 'str', *, session_context: 'SessionContext | dict[str, Any] | None' = None, top_k: 'int | None' = None, max_chars: 'int "
                       "| None' = None, companion_bot_mood: 'str' = '', companion_bot_energy: 'float' = 0.0, p5_attestation: 'Any' = None, "
                       "p5_attestation_consumer: 'Any' = None) -> 'str'",
                       True,
                       'recall'),
 'compose_context': ("(self, *, query: 'str' = '', session_context: 'SessionContext | dict[str, Any] | None' = None, top_k: 'int | None' = None, max_chars: "
                     "'int | None' = None, companion_bot_mood: 'str' = '', companion_bot_energy: 'float' = 0.0, retrieval_profile: 'str' = '', p5_attestation: "
                     "'Any' = None, p5_attestation_consumer: 'Any' = None) -> 'str'",
                     True,
                     'recall'),
 'remember': ("(self, *, event: 'Any', content: 'str', note_type: 'str' = 'memory') -> 'dict[str, Any]'", True, 'recall'),
 'recall': ("(self, *, event: 'Any', query: 'str', top_k: 'int' = 5, p5_attestation: 'Any' = None, p5_attestation_consumer: 'Any' = None) -> 'dict[str, Any]'",
            True,
            'recall'),
 'p5_capability_status': ("(self) -> 'dict[str, Any]'", False, 'maintenance'),
 'provenance_snapshot': ("(self) -> 'dict[str, Any]'", False, 'maintenance'),
 'provenance_preview': ("(self, candidates: 'list[dict[str, Any]]', *, operation_ref_hash: 'str') -> 'dict[str, Any]'", False, 'maintenance'),
 'provenance_apply': ("(self, operation: 'dict[str, Any]') -> 'dict[str, Any]'", True, 'maintenance'),
 'provenance_backup': ("(self) -> 'dict[str, Any]'", True, 'maintenance'),
 'provenance_rollback': ("(self, operation: 'dict[str, Any]') -> 'dict[str, Any]'", True, 'maintenance'),
 'create_note': ("(self, *, event: 'Any', title: 'str', content: 'str' = '') -> 'dict[str, Any]'", True, 'maintenance'),
 'read_notes': ("(self, *, event: 'Any', query: 'str' = '', limit: 'int' = 5) -> 'dict[str, Any]'", True, 'maintenance'),
 'delete_note': ("(self, *, event: 'Any', memory_id: 'str' = '', title: 'str' = '') -> 'dict[str, Any]'", True, 'maintenance'),
 'coordination_status': ("(self) -> 'dict[str, Any]'", False, 'maintenance'),
 'consume_person_projection': ("(self, projection: 'Any', expected_identity_key: 'str' = '', expected_person_id: 'str' = '', *, companion_available: 'bool' = "
                               "True) -> 'dict[str, Any]'",
                               False,
                               'scoped_namespace'),
 'consume_context_projection': ("(self, context: 'Any', expected_person_id: 'str' = '', expected_scope: 'str' = '', *, companion_available: 'bool' = True) -> "
                                "'dict[str, Any]'",
                                False,
                                'scoped_namespace'),
 'probe_capability_snapshot': ("(self) -> 'dict[str, Any]'", False, 'producer'),
 'probe_bot_personal_memory_capabilities': ("(self) -> 'dict[str, Any]'", False, 'producer'),
 'probe_namespace_context_capabilities': ("(self) -> 'dict[str, Any]'", False, 'scoped_namespace'),
 'bind_namespace_migration_epoch': ("(self, capability: 'Any', *, operation_id: 'str', expected_previous_epoch: 'str', migration_epoch: 'str', policy_version: "
                                    "'str') -> 'dict[str, Any]'",
                                    False,
                                    'scoped_namespace'),
 'upsert_scoped_record': ("(self, capability: 'Any', namespace: 'Any', *, record_kind: 'str', record_id: 'str', revision: 'int', payload: 'dict[str, Any]', "
                          "event_id: 'str') -> 'dict[str, Any]'",
                          False,
                          'scoped_namespace'),
 'read_scoped_record': ("(self, capability: 'Any', namespace: 'Any', *, record_kind: 'str', record_id: 'str') -> 'dict[str, Any]'", False, 'scoped_namespace'),
 'list_scoped_records': ("(self, capability: 'Any', namespace: 'Any', *, record_kind: 'str', limit: 'int' = 100) -> 'dict[str, Any]'",
                         False,
                         'scoped_namespace'),
 'tombstone_scoped_record': ("(self, capability: 'Any', namespace: 'Any', *, record_kind: 'str', record_id: 'str', revision: 'int', event_id: 'str') -> "
                             "'dict[str, Any]'",
                             False,
                             'scoped_namespace'),
 'tombstone_scoped_namespace': ("(self, capability: 'Any', namespace: 'Any', *, operation_id: 'str', reason_code: 'str') -> 'dict[str, Any]'",
                                False,
                                'scoped_namespace'),
 'tombstone_scoped_identity_scopes': ("(self, capability: 'Any', namespace: 'Any', *, operation_id: 'str', reason_code: 'str') -> 'dict[str, Any]'",
                                      False,
                                      'scoped_namespace'),
 'erase_scoped_group_scopes': ("(self, capability: 'Any', namespace: 'Any', *, operation_id: 'str', reason_code: 'str' = 'group_reset') -> 'dict[str, Any]'",
                               False,
                               'scoped_namespace'),
 'erase_scoped_persona_scopes': ("(self, capability: 'Any', namespace: 'Any', *, operation_id: 'str', reason_code: 'str' = 'persona_reset') -> 'dict[str, "
                                 "Any]'",
                                 False,
                                 'scoped_namespace'),
 'capability_status': ("(self) -> 'dict[str, Any]'", False, 'producer'),
 'mark_capability_negative': ("(self, reason: 'str') -> 'dict[str, Any]'", False, 'producer'),
 'get_token_usage_summary': ("(self) -> 'dict[str, Any]'", False, 'recall'),
 'should_defer_private_companion_section': ("(self, section: 'str') -> 'bool'", False, 'recall'),
 'create_cross_window_thread': ("(self, *, from_session: 'str', to_session: 'str', topic: 'str', content: 'str', visibility: 'str' = 'shareable', metadata: "
                                "'dict[str, Any] | None' = None) -> 'str'",
                                True,
                                'maintenance'),
 'mark_visibility': ("(self, memory_id: 'str', visibility: 'str') -> 'bool'", True, 'recall'),
 'get_emotional_events': ("(self, *, session_id: 'str' = '', limit: 'int' = 5) -> 'list[dict[str, Any]]'", False, 'portrait_emotion'),
 'list_emotion_events': ("(self, *, delivery_context: 'Any' = None, cursor: 'str' = '', limit: 'int' = 10, **_legacy: 'Any') -> 'dict[str, Any]'",
                         True,
                         'portrait_emotion'),
 'ack_emotion_events': ("(self, event_refs: 'list[dict[str, Any]]', *, delivery_context: 'Any' = None, **_legacy: 'Any') -> 'dict[str, Any]'",
                        True,
                        'portrait_emotion'),
 'record_emotion_event': ("(self, event: 'dict[str, Any]', *, producer_context: 'Any' = None) -> 'dict[str, Any]'", True, 'portrait_emotion'),
 'revise_emotion_event': ("(self, event: 'dict[str, Any]', *, producer_context: 'Any' = None) -> 'dict[str, Any]'", True, 'portrait_emotion'),
 'get_emotion_trace': ("(self, trace_id: 'str', *, requester_context: 'Any' = None, limit: 'int' = 100) -> 'dict[str, Any]'", True, 'portrait_emotion'),
 'get_emotion_trace_diagnostic': ("(self, trace_id: 'str', requester_context: 'Any', *, limit: 'int' = 100) -> 'dict[str, Any]'", True, 'portrait_emotion'),
 'get_emotion_trace_summary': ("(self, requester_context: 'Any', *, cursor: 'str' = '', limit: 'int' = 20) -> 'dict[str, Any]'", True, 'portrait_emotion'),
 'search_open_loops': ("(self, *, session_id: 'str' = '', limit: 'int' = 3) -> 'list[dict[str, Any]]'", True, 'recall'),
 'get_relationship_phase': ("(self, *, session_id: 'str' = '', scope: 'str' = 'private', platform: 'str' = '', user_id: 'str' = '', group_id: 'str' = '', "
                            "bot_id: 'str' = '') -> 'dict[str, Any]'",
                            False,
                            'portrait_emotion'),
 'peek_relationship_phase': ("(self, *, session_id: 'str' = '', scope: 'str' = 'private', platform: 'str' = '', user_id: 'str' = '', group_id: 'str' = '', "
                             "bot_id: 'str' = '') -> 'dict[str, Any]'",
                             False,
                             'portrait_emotion'),
 'get_recent_emotional_state': ("(self, *, exclude_session_id: 'str' = '', window_seconds: 'float' = 1800.0, limit: 'int' = 5) -> 'dict[str, Any]'",
                                False,
                                'portrait_emotion')}

PUBLIC_API_FINGERPRINT = '7ba8da2fb14540ed9f2b6b805d193379a3218ba3b7cb50638ba58f79b1924a87'

FAMILY_TYPES = {
    "recall": ("_recall_family", RecallBridgeFamily, "bridge_recall.py"),
    "external_record": ("_external_record_family", ExternalRecordBridgeFamily, "bridge_external_record.py"),
    "scoped_namespace": ("_scoped_namespace_family", ScopedNamespaceBridgeFamily, "bridge_scoped_namespace.py"),
    "portrait_emotion": ("_portrait_emotion_family", PortraitEmotionBridgeFamily, "bridge_portrait_emotion.py"),
    "producer": ("_producer_family", ProducerBridgeFamily, "bridge_producer.py"),
    "maintenance": ("_maintenance_family", MaintenanceBridgeFamily, "bridge_maintenance.py"),
}

RETAINED_IN_FACADE = frozenset({'bind_emotion_page_api',
           'bridge_lifecycle_status',
           'consume_context_projection',
           'consume_expression_decision',
           'consume_person_projection',
           'consume_relationship_projection',
           'create_emotion_admin_context',
           'create_emotion_delivery_context',
           'create_emotion_producer_context',
           'create_external_memory_context',
           'create_user_memory_context',
           'deactivate',
           'record_external_memory',
           'register_bot_personal_producer',
           'register_emotion_producer',
           'register_external_memory_producer',
           'register_private_companion'})

ALIAS_TARGETS = {
    ("external_record", "record_bot_action"): "record_event",
    ("external_record", "record_persona_life"): "record_event",
    ("external_record", "record_proactive_message"): "record_event",
    ("external_record", "record_shared_experience"): "record_event",
    ("external_record", "record_search_action"): "record_event",
    ("external_record", "record_creative_work"): "record_event",
    ("external_record", "record_image_action"): "record_event",
    ("external_record", "record_qzone_action"): "record_event",
    ("external_record", "record_reading"): "record_event",
    ("external_record", "record_schedule_fragment"): "record_event",
    ("external_record", "record_bot_personal_memory"): "record_bot_personal_archive",
    ("recall", "search_bot_personal_profile"): "read_bot_personal_profile",
    ("recall", "read_profile"): "read_bot_profile",
    ("portrait_emotion", "get_emotion_trace"): "get_emotion_trace_diagnostic",
    ("producer", "probe_capability_snapshot"): "capability_status",
    ("producer", "probe_bot_personal_memory_capabilities"): "probe_capability_snapshot",
    ("producer", "mark_capability_negative"): "capability_status",
}


def _public_methods(cls: type) -> dict[str, object]:
    return {
        name: value
        for name, value in cls.__dict__.items()
        if not name.startswith("_") and inspect.isfunction(value)
    }


def _required_call(function: object) -> tuple[list[object], dict[str, object]]:
    args: list[object] = []
    kwargs: dict[str, object] = {}
    for parameter in list(inspect.signature(function).parameters.values())[1:]:
        if parameter.default is not inspect.Parameter.empty:
            continue
        if parameter.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
            continue
        value = object()
        if parameter.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}:
            args.append(value)
        else:
            kwargs[parameter.name] = value
    return args, kwargs


def _method_node(path: Path, class_name: str, method_name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    return next(
        node
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name
    )


class BridgeFamilyPublicContractTests(unittest.TestCase):
    def test_hard_coded_manifest_locks_all_public_descriptors(self) -> None:
        methods = _public_methods(bridge.MemoryCompanionBridge)
        self.assertEqual(84, len(PUBLIC_API))
        self.assertEqual(set(PUBLIC_API), set(methods))
        self.assertEqual(
            {"recall": 13, "external_record": 15, "scoped_namespace": 12,
             "portrait_emotion": 17, "producer": 14, "maintenance": 13},
            {family: len(names) for family, names in FAMILY_METHODS.items()},
        )
        self.assertEqual(set(PUBLIC_API), {name for names in FAMILY_METHODS.values() for name in names})

        rows = []
        for name in sorted(PUBLIC_API):
            expected_signature, expected_async, expected_family = PUBLIC_API[name]
            descriptor = inspect.getattr_static(bridge.MemoryCompanionBridge, name)
            self.assertIs(descriptor, methods[name])
            self.assertTrue(inspect.isfunction(descriptor))
            self.assertEqual(expected_signature, str(inspect.signature(descriptor)))
            self.assertEqual(expected_async, inspect.iscoroutinefunction(descriptor))
            self.assertEqual(name, descriptor.__name__)
            self.assertEqual(f"MemoryCompanionBridge.{name}", descriptor.__qualname__)
            self.assertEqual("core.bridge", descriptor.__module__)
            self.assertEqual(expected_family, PUBLIC_API[name][2])
            doc_fingerprint = hashlib.sha256((descriptor.__doc__ or "").encode()).hexdigest()
            rows.append(
                (name, expected_signature, expected_async, expected_family, type(descriptor).__name__,
                 descriptor.__qualname__, descriptor.__module__, doc_fingerprint)
            )
        fingerprint = hashlib.sha256(
            json.dumps(rows, ensure_ascii=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.assertEqual(PUBLIC_API_FINGERPRINT, fingerprint)

    def test_families_are_concrete_owner_only_objects(self) -> None:
        owner = bridge.MemoryCompanionBridge(object())
        for family, (attribute, family_type, _filename) in FAMILY_TYPES.items():
            with self.subTest(family=family):
                self.assertFalse(hasattr(bridge, family_type.__name__))
                instance = getattr(owner, attribute)
                self.assertIs(type(instance), family_type)
                self.assertIs(owner, instance._owner)
                self.assertFalse(hasattr(instance, "__dict__"))
                self.assertEqual(("_owner",), family_type.__slots__)
                self.assertEqual((object,), family_type.__bases__)
                self.assertNotIn("__getattr__", family_type.__dict__)

    def test_family_method_signatures_and_coroutine_shape_match_facade(self) -> None:
        for family, names in FAMILY_METHODS.items():
            _attribute, family_type, _filename = FAMILY_TYPES[family]
            for name in names:
                if name in RETAINED_IN_FACADE:
                    continue
                with self.subTest(family=family, method=name):
                    family_method = inspect.getattr_static(family_type, name)
                    facade_method = inspect.getattr_static(bridge.MemoryCompanionBridge, name)
                    self.assertEqual(str(inspect.signature(facade_method)), str(inspect.signature(family_method)))
                    self.assertEqual(
                        inspect.iscoroutinefunction(facade_method),
                        inspect.iscoroutinefunction(family_method),
                    )


class BridgeFamilyStaticDelegationTests(unittest.TestCase):
    def test_facade_uses_one_explicit_original_passthrough_per_moved_method(self) -> None:
        bridge_path = ROOT / "core" / "bridge.py"
        for name, (signature, expected_async, family) in PUBLIC_API.items():
            if name in RETAINED_IN_FACADE:
                continue
            node = _method_node(bridge_path, "MemoryCompanionBridge", name)
            statements = list(node.body)
            if statements and isinstance(statements[0], ast.Expr) and isinstance(statements[0].value, ast.Constant):
                statements.pop(0)
            with self.subTest(method=name):
                self.assertEqual(1, len(statements))
                self.assertIsInstance(statements[0], ast.Return)
                returned = statements[0].value
                call = returned.value if isinstance(returned, ast.Await) else returned
                self.assertEqual(expected_async, isinstance(returned, ast.Await))
                self.assertIsInstance(call, ast.Call)
                target = call.func
                self.assertIsInstance(target, ast.Attribute)
                self.assertEqual(name, target.attr)
                self.assertIsInstance(target.value, ast.Attribute)
                self.assertEqual(FAMILY_TYPES[family][0], target.value.attr)
                self.assertIsInstance(target.value.value, ast.Name)
                self.assertEqual("self", target.value.value.id)

                parameters = list(inspect.signature(inspect.getattr_static(bridge.MemoryCompanionBridge, name)).parameters.values())[1:]
                expected_positional = [
                    p.name for p in parameters
                    if p.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
                ]
                if any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in parameters):
                    expected_positional.append("*" + next(p.name for p in parameters if p.kind is inspect.Parameter.VAR_POSITIONAL))
                actual_positional = [
                    "*" + arg.value.id if isinstance(arg, ast.Starred) else arg.id
                    for arg in call.args
                ]
                self.assertEqual(expected_positional, actual_positional)
                expected_keywords = [
                    (p.name, p.name) for p in parameters if p.kind is inspect.Parameter.KEYWORD_ONLY
                ]
                if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters):
                    var_keyword = next(p.name for p in parameters if p.kind is inspect.Parameter.VAR_KEYWORD)
                    expected_keywords.append((None, var_keyword))
                actual_keywords = [(keyword.arg, keyword.value.id) for keyword in call.keywords]
                self.assertEqual(expected_keywords, actual_keywords)

    def test_family_modules_have_no_bridge_import_or_dynamic_dispatch_scaffolding(self) -> None:
        for family, (_attribute, family_type, filename) in FAMILY_TYPES.items():
            path = ROOT / "core" / filename
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports = {
                node.module or ""
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
            }
            imported_names = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            }
            imported_from_names = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names
            }
            calls = {
                node.func.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            dynamic_import_calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and (
                    isinstance(node.func, ast.Name) and node.func.id == "__import__"
                    or isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "importlib"
                    and node.func.attr == "import_module"
                )
            ]
            with self.subTest(family=family):
                self.assertFalse({"bridge", "core.bridge"} & (imports | imported_names))
                self.assertNotIn("bridge", imported_from_names)
                self.assertEqual([], dynamic_import_calls)
                self.assertFalse({"setattr", "exec", "eval", "__import__"} & calls)
                self.assertNotIn("__getattr__", family_type.__dict__)
                public = {
                    name for name, value in family_type.__dict__.items()
                    if not name.startswith("_") and inspect.isfunction(value)
                }
                self.assertEqual(set(FAMILY_METHODS[family]) - RETAINED_IN_FACADE, public)

    def test_authority_state_and_validators_remain_in_the_facade(self) -> None:
        bridge_source = (ROOT / "core" / "bridge.py").read_text(encoding="utf-8")
        family_source = "\n".join(
            (ROOT / "core" / filename).read_text(encoding="utf-8")
            for _attribute, _family_type, filename in FAMILY_TYPES.values()
        )
        for marker in (
            "_COMPANION_PROJECTION_SECRET = secrets.token_bytes(32)",
            "self.__scoped_store",
            "self._capability_cache = CapabilityCache()",
            "self._emotion_producer_token = object()",
            "self._external_memory_producer_token = object()",
            "self._emotion_page_admin_token = object()",
            "def _authorized_scoped_context",
            "def _is_valid_external_memory_producer_capability",
            "def _is_valid_emotion_producer_capability",
            "async def record_external_memory",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, bridge_source)
                self.assertNotIn(marker, family_source)

        for _family, (_attribute, _family_type, filename) in FAMILY_TYPES.items():
            tree = ast.parse((ROOT / "core" / filename).read_text(encoding="utf-8"))
            owner_state_assignments = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
                and isinstance(node.ctx, (ast.Store, ast.Del))
                and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"
                and node.value.attr == "_owner"
            ]
            self.assertEqual([], owner_state_assignments)

    def test_compatibility_aliases_call_owner_facade_for_dynamic_dispatch(self) -> None:
        for (family, alias), target_name in ALIAS_TARGETS.items():
            _attribute, family_type, filename = FAMILY_TYPES[family]
            node = _method_node(ROOT / "core" / filename, family_type.__name__, alias)
            calls = [
                call
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == target_name
                and isinstance(call.func.value, ast.Attribute)
                and call.func.value.attr == "_owner"
                and isinstance(call.func.value.value, ast.Name)
                and call.func.value.value.id == "self"
            ]
            with self.subTest(alias=alias, target=target_name):
                self.assertEqual(1, len(calls))


class BridgeFamilyRuntimeDelegationTests(unittest.TestCase):
    def test_every_moved_wrapper_preserves_result_and_exception_identity(self) -> None:
        owner = bridge.MemoryCompanionBridge(object())
        for name, (_signature, expected_async, family) in PUBLIC_API.items():
            if name in RETAINED_IN_FACADE:
                continue
            attribute, family_type, _filename = FAMILY_TYPES[family]
            args, kwargs = _required_call(inspect.getattr_static(bridge.MemoryCompanionBridge, name))
            sentinel = object()

            if expected_async:
                async def return_sentinel(_family_self, *unused_args, **unused_kwargs):
                    return sentinel

                with patch.object(family_type, name, return_sentinel):
                    result = asyncio.run(getattr(owner, name)(*args, **kwargs))
            else:
                def return_sentinel(_family_self, *unused_args, **unused_kwargs):
                    return sentinel

                with patch.object(family_type, name, return_sentinel):
                    result = getattr(owner, name)(*args, **kwargs)
            with self.subTest(method=name, behavior="identity"):
                self.assertIs(sentinel, result)
                self.assertIs(owner, getattr(owner, attribute)._owner)

            failure = RuntimeError(f"family-failure:{name}")
            if expected_async:
                async def raise_failure(_family_self, *unused_args, **unused_kwargs):
                    raise failure

                with patch.object(family_type, name, raise_failure):
                    with self.assertRaises(RuntimeError) as raised:
                        asyncio.run(getattr(owner, name)(*args, **kwargs))
            else:
                def raise_failure(_family_self, *unused_args, **unused_kwargs):
                    raise failure

                with patch.object(family_type, name, raise_failure):
                    with self.assertRaises(RuntimeError) as raised:
                        getattr(owner, name)(*args, **kwargs)
            with self.subTest(method=name, behavior="exception"):
                self.assertIs(failure, raised.exception)

    def test_aliases_keep_owner_monkeypatch_dispatch(self) -> None:
        owner = bridge.MemoryCompanionBridge(object())
        sentinel = object()

        async def record_event(**kwargs):
            return sentinel

        owner.record_event = record_event
        self.assertIs(sentinel, asyncio.run(owner.record_bot_action(content="x")))

        archive = object()
        async def record_archive(envelope, **kwargs):
            self.assertIs(archive, envelope)
            return sentinel

        owner.record_bot_personal_archive = record_archive
        with patch("core.bridge_external_record.build_bot_personal_archive", return_value=archive):
            self.assertIs(
                sentinel,
                asyncio.run(owner.record_bot_personal_memory(memory_type="conversation_summary")),
            )

        async def read_bot_profile(*args, **kwargs):
            return sentinel

        owner.read_bot_profile = read_bot_profile
        self.assertIs(sentinel, asyncio.run(owner.read_profile("bot_creative")))

        async def trace_diagnostic(*args, **kwargs):
            return sentinel

        owner.get_emotion_trace_diagnostic = trace_diagnostic
        self.assertIs(sentinel, asyncio.run(owner.get_emotion_trace("trace-1")))

        marker = object()
        owner.probe_capability_snapshot = lambda: {"marker": marker}
        self.assertIs(marker, owner.probe_bot_personal_memory_capabilities()["marker"])
        owner.capability_status = lambda: sentinel
        self.assertIs(sentinel, owner.mark_capability_negative("test"))

    def test_fresh_import_and_hot_reload_revoke_old_capabilities_in_subprocess(self) -> None:
        code = r"""
import importlib
from types import SimpleNamespace
import core.bridge as module

assert len([
    name for name, value in module.MemoryCompanionBridge.__dict__.items()
    if not name.startswith("_") and callable(value)
]) == 84

class Companion:
    pass

companion = Companion()
metadata = SimpleNamespace(
    star_cls=companion,
    star_cls_type=type(companion),
    root_dir_name="astrbot_plugin_private_companion",
    name="PrivateCompanion",
    activated=True,
)
plugin = SimpleNamespace(context=SimpleNamespace(get_all_stars=lambda: [metadata]))
old_bridge = module.MemoryCompanionBridge(plugin)
old_capability = old_bridge.register_emotion_producer(companion)
assert old_capability is not None
old_bridge.deactivate()
assert old_bridge.create_emotion_producer_context(
    old_capability,
    bot_id="bot-1",
    scope="private",
    platform="qq",
    user_id="u1",
    session_id="qq:FriendMessage:u1",
) is None

module = importlib.reload(module)
new_bridge = module.MemoryCompanionBridge(plugin)
new_capability = new_bridge.register_emotion_producer(companion)
assert new_capability is not None
assert new_bridge.create_emotion_producer_context(
    old_capability,
    bot_id="bot-1",
    scope="private",
    platform="qq",
    user_id="u1",
    session_id="qq:FriendMessage:u1",
) is None
assert new_bridge.create_emotion_producer_context(
    new_capability,
    bot_id="bot-1",
    scope="private",
    platform="qq",
    user_id="u1",
    session_id="qq:FriendMessage:u1",
) is not None
"""
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)


if __name__ == "__main__":
    unittest.main()
