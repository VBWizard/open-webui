"""
memchat_db.py — Bridge between Open WebUI memory system and the memchat Postgres schema.

Stores and retrieves conversation memories using the existing memchat.messages table,
which already contains 1+ year of embedded conversation history (BAAI/bge-base-en-v1.5, 768-dim).
"""

import asyncio
import json
import logging
import os
import uuid
from typing import Optional

import httpx
import psycopg2
import psycopg2.pool
import psycopg2.extras

from open_webui.retrieval.vector.main import SearchResult
from open_webui.config import MEMCHAT_EMBED_CONNECTION_IDX, MEMCHAT_EMBED_MODEL, OPENAI_API_BASE_URLS

log = logging.getLogger(__name__)

MEMCHAT_DB_URL = os.environ.get(
    "MEMCHAT_DB_URL",
    "postgresql://postgres:Hi10081113@172.27.160.1:5432/memchat_db",
)
MEMCHAT_MIN_SCORE = float(os.environ.get("MEMCHAT_MIN_SCORE", "0.70"))
MEMCHAT_K = int(os.environ.get("MEMCHAT_K", "6"))
MEMCHAT_CONTEXT_STEPS = int(os.environ.get("MEMCHAT_CONTEXT_STEPS", "4"))
MEMCHAT_MAX_MSG_CHARS = int(os.environ.get("MEMCHAT_MAX_MSG_CHARS", "2000"))

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 10, MEMCHAT_DB_URL, connect_timeout=5)
    return _pool


def _get_conn():
    return _get_pool().getconn()


def _put_conn(conn):
    _get_pool().putconn(conn)


def _vec_literal(v: list[float]) -> str:
    return "[" + ",".join(map(str, v)) + "]"


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


async def get_embedding(text: str) -> list[float]:
    """Call the configured OpenAI-compatible embeddings endpoint."""
    idx = int(MEMCHAT_EMBED_CONNECTION_IDX.value)
    urls = OPENAI_API_BASE_URLS.value
    if idx < 0 or idx >= len(urls):
        raise RuntimeError(
            f"Invalid embedding connection index {idx}. "
            f"Select a valid connection in Admin > Interface > Memory Embedding."
        )
    url = f"{urls[idx].rstrip('/')}/embeddings"
    model = str(MEMCHAT_EMBED_MODEL)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                json={"input": text, "model": model},
                headers={"Authorization": "Bearer lm-studio"},
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
    except httpx.ConnectTimeout:
        raise RuntimeError(
            f"Embedding service unreachable at {url}. "
            f"Is the embedding server running? (Admin > Interface > Memory Embedding)"
        )
    except httpx.ConnectError:
        raise RuntimeError(
            f"Cannot connect to embedding service at {url}. "
            f"Check the URL in Admin > Interface > Memory Embedding."
        )


# ---------------------------------------------------------------------------
# Memory search & storage (used by memories router)
# ---------------------------------------------------------------------------

MIN_CONTENT_LENGTH = 20  # ignore messages shorter than this


def _fetch_one(cur, msg_id: str) -> Optional[dict]:
    cur.execute(
        "SELECT id::text, parent_id::text, author_role, content, timestamp FROM memchat.messages WHERE id = %s::uuid",
        (msg_id,),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def _fetch_context_sync(conn, hit_id: str, steps: Optional[int] = None) -> list[dict]:
    """
    Walk the parent_id chain `steps` up and down from hit_id.
    For descendants, follows the oldest child at each step (avoids branch explosion).
    Returns messages in conversation order (oldest first), including the hit itself.
    """
    n = steps if steps is not None else MEMCHAT_CONTEXT_STEPS
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Walk UP via parent_id
        ancestors = []
        current_id = hit_id
        for _ in range(n):
            row = _fetch_one(cur, current_id)
            if not row or not row.get("parent_id"):
                break
            parent = _fetch_one(cur, row["parent_id"])
            if not parent:
                break
            ancestors.append(parent)
            current_id = parent["id"]
        ancestors.reverse()  # oldest first

        # Fetch the hit itself
        hit = _fetch_one(cur, hit_id)
        if not hit:
            return ancestors

        # Walk DOWN: at each step take the oldest child (avoids branch explosion)
        descendants = []
        current_id = hit_id
        for _ in range(n):
            cur.execute(
                """
                SELECT id::text, parent_id::text, author_role, content, timestamp
                FROM memchat.messages
                WHERE parent_id = %s::uuid
                  AND content IS NOT NULL AND content != ''
                ORDER BY timestamp
                LIMIT 1
                """,
                (current_id,),
            )
            child = cur.fetchone()
            if not child:
                break
            descendants.append(dict(child))
            current_id = child["id"]

    return ancestors + [hit] + descendants


def _truncate(content: str, max_chars: int = 0) -> str:
    """Truncate content to max_chars, appending an indicator if cut. 0 = no limit."""
    limit = max_chars if max_chars > 0 else MEMCHAT_MAX_MSG_CHARS
    if limit <= 0 or len(content) <= limit:
        return content
    return content[:limit] + f"… [+{len(content) - limit} chars]"


def _format_context(msgs: list[dict]) -> str:
    parts = []
    for msg in msgs:
        role = (msg.get("author_role") or "unknown").strip()
        content = _truncate((msg.get("content") or "").strip())
        if content:
            parts.append(f"{role}: {content}")
    return "\n".join(parts)


def _format_context_with_timestamps(msgs: list[dict]) -> str:
    parts = []
    for msg in msgs:
        role = (msg.get("author_role") or "unknown").strip()
        content = _truncate((msg.get("content") or "").strip())
        ts = msg.get("timestamp")
        ts_str = f'[{ts.strftime("%Y-%m-%d %H:%M:%S")}] ' if ts else ''
        if content:
            parts.append(f"{ts_str}{role}: {content}")
    return "\n".join(parts)


def _search_memories_with_context_sync(
    user_id: str, vector: list[float], k: int,
    exclude_chat_id: Optional[str] = None,
    after: Optional[str] = None,
    before: Optional[str] = None,
) -> Optional[SearchResult]:
    conn = _get_conn()
    try:
        # Step 1: semantic hits
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            vec_lit = _vec_literal(vector)
            cur.execute(
                """
                SELECT m.id::text,
                       m.content,
                       m.metadata,
                       m.timestamp,
                       EXTRACT(EPOCH FROM m.timestamp)::bigint AS ts_epoch,
                       1 - (m.embedding <=> %s::vector) AS score
                FROM memchat.messages m
                JOIN memchat.conversations c ON m.conversation_id = c.id
                WHERE c.user_id = %s
                  AND m.embedding IS NOT NULL
                  AND m.content IS NOT NULL
                  AND length(m.content) >= %s
                  AND m.author_role IN ('user', 'assistant')
                  AND (c.metadata->>'deleted' IS NULL)
                  AND (
                      %s IS NULL
                      OR c.metadata->>'owui_chat_id' IS NULL
                      OR c.metadata->>'owui_chat_id' != %s
                  )
                  AND (%s IS NULL OR m.timestamp >= %s::timestamp)
                  AND (%s IS NULL OR m.timestamp < %s::timestamp)
                ORDER BY m.embedding <=> %s::vector
                LIMIT %s
                """,
                (vec_lit, user_id, MIN_CONTENT_LENGTH,
                 exclude_chat_id, exclude_chat_id,
                 after, after,
                 before, before,
                 vec_lit, k),
            )
            hits = cur.fetchall()

        if not hits:
            return None

        # Filter out hits below the minimum score threshold
        hits = [h for h in hits if float(h["score"]) >= MEMCHAT_MIN_SCORE]
        if not hits:
            return None

        # Step 2: fetch context for each hit, deduplicate across all contexts
        seen_ids: set[str] = set()
        seen_contents: set[str] = set()
        context_groups: list[list[dict]] = []

        for hit in hits:
            raw = _fetch_context_sync(conn, hit["id"])
            deduped = []
            for msg in raw:
                msg_id = msg["id"]
                normalized = (msg.get("content") or "").strip().lower()
                if msg_id in seen_ids or (normalized and normalized in seen_contents):
                    continue
                seen_ids.add(msg_id)
                if normalized:
                    seen_contents.add(normalized)
                deduped.append(msg)
            if deduped:
                context_groups.append(deduped)

        if not context_groups:
            return None

        # Step 3: format each context group as a conversation snippet
        documents = [_format_context(group) for group in context_groups]
        scores = [float(h["score"]) for h in hits[: len(context_groups)]]
        ids = [h["id"] for h in hits[: len(context_groups)]]
        metadatas = [
            {**(h["metadata"] or {}), "created_at": h["ts_epoch"]}
            for h in hits[: len(context_groups)]
        ]

        return SearchResult(
            ids=[ids],
            documents=[documents],
            metadatas=[metadatas],
            distances=[scores],
        )
    finally:
        _put_conn(conn)


async def search_memories(
    user_id: str, vector: list[float], k: int = 3,
    exclude_chat_id: Optional[str] = None,
    after: Optional[str] = None,
    before: Optional[str] = None,
) -> Optional[SearchResult]:
    return await asyncio.to_thread(
        _search_memories_with_context_sync, user_id, vector, k, exclude_chat_id, after, before
    )


def _get_or_create_memory_conversation(conn, user_id: str) -> str:
    """Return the ID of the 'OpenWebUI Memories' conversation for this user, creating it if needed."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM memchat.conversations
            WHERE user_id = %s AND title = 'OpenWebUI Memories'
            LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if row:
            return str(row[0])
        conv_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO memchat.conversations (id, title, user_id, create_time, update_time, metadata)
            VALUES (%s::uuid, 'OpenWebUI Memories', %s, NOW(), NOW(), '{}')
            """,
            (conv_id, user_id),
        )
        return conv_id


def _upsert_memory_sync(user_id: str, memory_id: str, content: str, vector: list[float], metadata: dict) -> None:
    conn = _get_conn()
    try:
        conv_id = _get_or_create_memory_conversation(conn, user_id)
        vec_lit = _vec_literal(vector)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memchat.messages
                    (id, conversation_id, content, embedding, metadata, timestamp, author_role, vendor)
                VALUES (%s::uuid, %s::uuid, %s, %s::vector, %s, NOW(), 'memory', 'openwebui')
                ON CONFLICT (id) DO UPDATE SET
                    content    = EXCLUDED.content,
                    embedding  = EXCLUDED.embedding,
                    metadata   = EXCLUDED.metadata
                """,
                (memory_id, conv_id, content, vec_lit, json.dumps(metadata or {})),
            )
        conn.commit()
    finally:
        _put_conn(conn)


async def upsert_memory(user_id: str, memory_id: str, content: str, vector: list[float], metadata: dict) -> None:
    await asyncio.to_thread(_upsert_memory_sync, user_id, memory_id, content, vector, metadata)


def _delete_memory_sync(user_id: str, memory_id: str) -> None:
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM memchat.messages m
                USING memchat.conversations c
                WHERE m.conversation_id = c.id
                  AND c.user_id = %s
                  AND m.id = %s::uuid
                """,
                (user_id, memory_id),
            )
        conn.commit()
    finally:
        _put_conn(conn)


async def delete_memory(user_id: str, memory_id: str) -> None:
    await asyncio.to_thread(_delete_memory_sync, user_id, memory_id)


def _delete_all_memories_sync(user_id: str) -> None:
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM memchat.messages m
                USING memchat.conversations c
                WHERE m.conversation_id = c.id
                  AND c.user_id = %s
                  AND c.title = 'OpenWebUI Memories'
                """,
                (user_id,),
            )
        conn.commit()
    finally:
        _put_conn(conn)


async def delete_all_memories(user_id: str) -> None:
    await asyncio.to_thread(_delete_all_memories_sync, user_id)


STATIC_MEMORY_MAX_CHARS = 500


def _fetch_static_memories_sync(user_id: str) -> list[str]:
    """Return all saved (author_role='memory') records for the user, each capped at STATIC_MEMORY_MAX_CHARS."""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT m.content
                FROM memchat.messages m
                JOIN memchat.conversations c ON m.conversation_id = c.id
                WHERE c.user_id = %s
                  AND m.author_role = 'memory'
                  AND m.content IS NOT NULL
                  AND length(m.content) > 0
                ORDER BY m.timestamp ASC
                """,
                (user_id,),
            )
            rows = cur.fetchall()
        result = []
        for row in rows:
            content = row['content']
            if len(content) > STATIC_MEMORY_MAX_CHARS:
                content = content[:STATIC_MEMORY_MAX_CHARS] + '…'
            result.append(content)
        return result
    finally:
        _put_conn(conn)


async def fetch_static_memories(user_id: str) -> list[str]:
    return await asyncio.to_thread(_fetch_static_memories_sync, user_id)


def _fetch_static_memories_with_meta_sync(user_id: str) -> list[dict]:
    """Return all static (author_role='memory') records for the user with id, content, created_at."""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT m.id::text, m.content, m.timestamp
                FROM memchat.messages m
                JOIN memchat.conversations c ON m.conversation_id = c.id
                WHERE c.user_id = %s
                  AND m.author_role = 'memory'
                  AND m.content IS NOT NULL
                  AND length(m.content) > 0
                ORDER BY m.timestamp ASC
                """,
                (user_id,),
            )
            rows = cur.fetchall()
        result = []
        for row in rows:
            content = row['content']
            if len(content) > STATIC_MEMORY_MAX_CHARS:
                content = content[:STATIC_MEMORY_MAX_CHARS] + '…'
            ts = row['timestamp']
            result.append({
                'id': row['id'],
                'content': content,
                'created_at': ts.strftime('%Y-%m-%d %H:%M:%S') if ts else 'Unknown',
            })
        return result
    finally:
        _put_conn(conn)


async def fetch_static_memories_with_meta(user_id: str) -> list[dict]:
    return await asyncio.to_thread(_fetch_static_memories_with_meta_sync, user_id)


def _get_messages_around_timestamp_sync(user_id: str, ts_str: str, steps: int) -> list[dict]:
    """Find the message closest to ts_str (ISO datetime) and walk the parent_id chain `steps` up/down."""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT m.id::text
                FROM memchat.messages m
                JOIN memchat.conversations c ON m.conversation_id = c.id
                WHERE c.user_id = %s
                  AND m.timestamp IS NOT NULL
                  AND m.author_role IN ('user', 'assistant')
                  AND (c.metadata->>'deleted' IS NULL)
                ORDER BY ABS(EXTRACT(EPOCH FROM (m.timestamp - %s::timestamp)))
                LIMIT 1
                """,
                (user_id, ts_str),
            )
            row = cur.fetchone()
            if not row:
                return []
        return _fetch_context_sync(conn, row['id'], steps=steps)
    finally:
        _put_conn(conn)


async def get_messages_around_timestamp(user_id: str, ts_str: str, steps: int = MEMCHAT_CONTEXT_STEPS) -> list[dict]:
    """Return messages around the given ISO timestamp via parent_id walk. No semantic search."""
    return await asyncio.to_thread(_get_messages_around_timestamp_sync, user_id, ts_str, steps)


# ---------------------------------------------------------------------------
# Soft-delete (exclude from search when chat deleted from UI)
# ---------------------------------------------------------------------------


def _soft_delete_chat_sync(user_id: str, owui_chat_id: str) -> None:
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE memchat.conversations
                SET metadata = metadata || '{"deleted": true}'::jsonb
                WHERE user_id = %s
                  AND metadata->>'owui_chat_id' = %s
                RETURNING id, title
                """,
                (user_id, owui_chat_id),
            )
            conv_rows = cur.fetchall()
            conv_affected = len(conv_rows)
            conv_id = str(conv_rows[0][0]) if conv_rows else None
            conv_title = conv_rows[0][1] if conv_rows else None
            cur.execute(
                """
                UPDATE memchat.messages m
                SET metadata = m.metadata || '{"deleted": true}'::jsonb
                FROM memchat.conversations c
                WHERE m.conversation_id = c.id
                  AND c.user_id = %s
                  AND c.metadata->>'owui_chat_id' = %s
                """,
                (user_id, owui_chat_id),
            )
            msg_affected = cur.rowcount
        conn.commit()
        log.info(f'[memchat] soft_delete_chat: user={user_id[:8]}... chat={owui_chat_id[:8]}... conv_id={conv_id} title={conv_title!r} conversations={conv_affected} messages={msg_affected}')
    finally:
        _put_conn(conn)


async def soft_delete_chat(user_id: str, owui_chat_id: str) -> None:
    await asyncio.to_thread(_soft_delete_chat_sync, user_id, owui_chat_id)


def _sync_chat_title_sync(user_id: str, owui_chat_id: str, title: str) -> None:
    log.info(f'[memchat] sync_chat_title: user={user_id[:8]}... chat={owui_chat_id[:8]}... title={title!r}')
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE memchat.conversations
                SET title = %s, update_time = NOW()
                WHERE user_id = %s
                  AND metadata->>'owui_chat_id' = %s
                  AND title != %s
                """,
                (title, user_id, owui_chat_id, title),
            )
            affected = cur.rowcount
        conn.commit()
        log.info(f'[memchat] sync_chat_title: rows_updated={affected}')
    except Exception as e:
        log.error(f'[memchat] sync_chat_title error: {e}')
    finally:
        _put_conn(conn)


async def sync_chat_title(user_id: str, owui_chat_id: str, title: str) -> None:
    await asyncio.to_thread(_sync_chat_title_sync, user_id, owui_chat_id, title)


def _soft_delete_all_chats_sync(user_id: str) -> None:
    """Mark all non-memory conversations for this user as deleted."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE memchat.conversations
                SET metadata = metadata || '{"deleted": true}'::jsonb
                WHERE user_id = %s
                  AND metadata->>'owui_chat_id' IS NOT NULL
                """,
                (user_id,),
            )
            conv_affected = cur.rowcount
            cur.execute(
                """
                UPDATE memchat.messages m
                SET metadata = m.metadata || '{"deleted": true}'::jsonb
                FROM memchat.conversations c
                WHERE m.conversation_id = c.id
                  AND c.user_id = %s
                  AND c.metadata->>'owui_chat_id' IS NOT NULL
                """,
                (user_id,),
            )
            msg_affected = cur.rowcount
        conn.commit()
        log.info(f'[memchat] soft_delete_all_chats: user={user_id[:8]}... conversations={conv_affected} messages={msg_affected}')
    finally:
        _put_conn(conn)


async def soft_delete_all_chats(user_id: str) -> None:
    await asyncio.to_thread(_soft_delete_all_chats_sync, user_id)


def _soft_delete_messages_sync(user_id: str, owui_message_ids: list[str]) -> None:
    if not owui_message_ids:
        return
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE memchat.messages m
                SET metadata = m.metadata || '{"deleted": true}'::jsonb
                FROM memchat.conversations c
                WHERE m.conversation_id = c.id
                  AND c.user_id = %s
                  AND m.owui_message_id = ANY(%s)
                """,
                (user_id, owui_message_ids),
            )
            affected = cur.rowcount
        conn.commit()
        log.info(f'[memchat] soft_delete_messages: user={user_id[:8]}... count={len(owui_message_ids)} affected={affected}')
    finally:
        _put_conn(conn)


async def soft_delete_messages(user_id: str, owui_message_ids: list[str]) -> None:
    await asyncio.to_thread(_soft_delete_messages_sync, user_id, owui_message_ids)


# ---------------------------------------------------------------------------
# Chat message storage (used by middleware outlet)
# ---------------------------------------------------------------------------


def _get_or_create_chat_conversation(conn, user_id: str, owui_chat_id: str, title: str) -> str:
    """Map an Open WebUI chat ID to a memchat conversation, creating it if needed."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM memchat.conversations
            WHERE user_id = %s
              AND metadata->>'owui_chat_id' = %s
            LIMIT 1
            """,
            (user_id, owui_chat_id),
        )
        row = cur.fetchone()
        if row:
            return str(row[0])
        conv_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO memchat.conversations (id, title, user_id, create_time, update_time, metadata)
            VALUES (%s::uuid, %s, %s, NOW(), NOW(), %s)
            """,
            (conv_id, title or "Open WebUI Chat", user_id, json.dumps({"owui_chat_id": owui_chat_id})),
        )
        return conv_id


def _lookup_uuid_by_owui_id(conn, owui_message_id: str) -> Optional[str]:
    """Return the memchat UUID for a message stored with the given owui_message_id."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM memchat.messages WHERE owui_message_id = %s LIMIT 1",
            (owui_message_id,),
        )
        row = cur.fetchone()
        return str(row[0]) if row else None


def _store_chat_message_sync(
    user_id: str,
    owui_chat_id: str,
    chat_title: str,
    role: str,
    content: str,
    vector: list[float],
    owui_message_id: str,
    parent_owui_id: Optional[str] = None,
    model_slug: Optional[str] = None,
) -> None:
    conn = _get_conn()
    try:
        conv_id = _get_or_create_chat_conversation(conn, user_id, owui_chat_id, chat_title)
        parent_uuid = _lookup_uuid_by_owui_id(conn, parent_owui_id) if parent_owui_id else None
        vec_lit = _vec_literal(vector)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memchat.messages
                    (id, conversation_id, parent_id, content, embedding, metadata, timestamp, author_role, vendor, owui_message_id, model_slug)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s::vector, %s, NOW(), %s, 'openwebui', %s, %s)
                ON CONFLICT (owui_message_id) WHERE owui_message_id IS NOT NULL DO NOTHING
                """,
                (
                    str(uuid.uuid4()),
                    conv_id,
                    parent_uuid,
                    content,
                    vec_lit,
                    json.dumps({"role": role, "owui_chat_id": owui_chat_id}),
                    role,
                    owui_message_id,
                    model_slug,
                ),
            )
        conn.commit()
    finally:
        _put_conn(conn)


async def store_chat_message(
    user_id: str,
    owui_chat_id: str,
    chat_title: str,
    role: str,
    content: str,
    owui_message_id: str,
    parent_owui_id: Optional[str] = None,
    model_slug: Optional[str] = None,
) -> None:
    """Embed a chat message and store it in memchat.messages. Silently skips duplicates."""
    if not content or not content.strip():
        return
    try:
        log.info(f"Getting embedding of user message to store to the messages table")
        vector = await get_embedding(content)
        log.info(f"Storing new record to the messages table")
        await asyncio.to_thread(
            _store_chat_message_sync,
            user_id, owui_chat_id, chat_title, role, content, vector, owui_message_id, parent_owui_id, model_slug,
        )
    except Exception as e:
        log.error(f"memchat store_chat_message error: {e}")
