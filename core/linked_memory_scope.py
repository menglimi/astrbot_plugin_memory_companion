"""Build exact-route read predicates; legacy summaries need every original event."""


def member_predicate(member, persona, reader):
    session, peer = member["session_id"], member["native_account_id"]
    identity = member.get("memory_identity", {})
    owner = identity.get("owner_bot_id", member["account_id"])
    if not isinstance(owner, str) or not owner.strip() or owner == "self":
        raise ValueError("verified native login required")
    meta = "CASE WHEN json_valid(m.metadata) THEN m.metadata ELSE '{}' END"
    persona_sql = f"COALESCE(json_extract({meta},'$.persona_id'),'')"
    direct = f"(m.owner_bot_id=? AND {persona_sql}=?)"
    args = [session, peer, peer, peer, reader, owner, persona]
    # This is an explicit host-issued capability, not an inference from a wxid.
    if identity.get("platform_name") == "wechat_native":
        refs = f"json_extract({meta},'$.source_event_ids')"
        tm = "CASE WHEN json_valid(t.metadata) THEN t.metadata ELSE '{}' END"
        proof = f"""(m.memory_type='conversation_summary' AND m.source_plugin='memory_companion'
            AND m.owner_bot_id IN (?, 'self', '') AND {persona_sql} IN ('', ?)
            AND json_type({meta},'$.source_event_ids')='array'
            AND json_array_length({refs}) BETWEEN 1 AND 256
            AND NOT EXISTS (SELECT 1 FROM json_each({refs}) ref
                LEFT JOIN timeline t ON t.id=ref.value
                WHERE ref.type!='text' OR t.id IS NULL OR t.scope!='private' OR t.session_id!=m.session_id
                OR COALESCE(json_extract({tm},'$.owner_bot_id'),'')!=?
                OR COALESCE(json_extract({tm},'$.bot_id'),?) NOT IN ('', ?)
                OR COALESCE(json_extract({tm},'$.persona_id'),'')!=?
                OR COALESCE(json_extract({tm},'$.platform'),'')!='wechat_native'
                OR t.event_type NOT IN ('user_message','bot_response')
                OR NOT ((t.event_type='user_message' AND t.subject_id=? AND t.object_id=?)
                    OR (t.event_type='bot_response' AND t.subject_id=? AND t.object_id=?))) )"""
        args.extend([owner, persona, owner, owner, owner, persona, peer, peer, owner, peer])
        direct = f"({direct} OR {proof})"
    clause = f"""(m.session_id=?
        AND (m.subject_kind!='user' OR m.subject_id IN ('',?))
        AND (m.object_kind!='user' OR m.object_id IN ('',?))
        AND NOT EXISTS (SELECT 1 FROM memory_acl_rules acl WHERE acl.enabled=1
            AND acl.effect='deny' AND acl.owner_scope='private' AND acl.reader_scope='private'
            AND acl.owner_id=? AND acl.reader_id=?)
        AND {direct}"""
    if member.get("since") is not None:
        clause += f""" AND julianday(m.created_at)>=julianday(?) AND julianday(m.occurred_at)>=julianday(?)
            AND (json_extract({meta},'$.start_at') IS NULL
                OR julianday(json_extract({meta},'$.start_at'))>=julianday(?))"""
        args.extend([member["since"]] * 3)
        if identity.get("platform_name") == "wechat_native":
            clause += f""" AND NOT EXISTS (SELECT 1 FROM json_each({meta},'$.source_event_ids') ref
                JOIN timeline t ON t.id=ref.value WHERE julianday(t.occurred_at) IS NULL
                OR julianday(t.occurred_at)<julianday(?))"""
            args.append(member["since"])
    return clause + ")", args
