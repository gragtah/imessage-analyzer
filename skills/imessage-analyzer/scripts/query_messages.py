#!/usr/bin/env python3
"""
Query iMessages database directly using SQLite.
Works around broken MCP server implementation.
"""

import sqlite3
import json
import sys
from datetime import datetime
from pathlib import Path


def get_db_path():
    """Get the path to the iMessages database."""
    home = Path.home()
    db_path = home / "Library" / "Messages" / "chat.db"
    if not db_path.exists():
        raise FileNotFoundError(f"Messages database not found at {db_path}")
    return str(db_path)


def decode_attributed_body(blob):
    """
    Extract the plain text from a message's attributedBody blob.

    Newer macOS versions often leave message.text NULL and store the body only
    in attributedBody: an NSAttributedString archived in Apple's undocumented
    "typedstream" format. The string payload follows the NSString class marker
    as a "+" type tag, a length (one byte, or 0x81/0x82 followed by a 2- or
    4-byte little-endian length), then UTF-8 bytes.

    Returns None if the blob is missing or doesn't match that layout.
    """
    if not blob:
        return None
    blob = bytes(blob)
    marker = blob.find(b"NSString")
    if marker == -1:
        return None
    tag = blob.find(b"+", marker + len(b"NSString"))
    if tag == -1 or tag - marker > 24:
        return None
    i = tag + 1
    if i >= len(blob):
        return None
    if blob[i] == 0x81:
        length, i = int.from_bytes(blob[i + 1:i + 3], "little"), i + 3
    elif blob[i] == 0x82:
        length, i = int.from_bytes(blob[i + 1:i + 5], "little"), i + 5
    else:
        length, i = blob[i], i + 1
    payload = blob[i:i + length]
    if len(payload) != length:
        return None
    return payload.decode("utf-8", errors="replace")


ATTACHMENT_MARKER = "\ufffc"  # stands in for an attachment inside message text

PHOTO_EXTENSIONS = {"heic", "heif", "jpg", "jpeg", "png", "gif", "webp", "tif", "tiff"}
VIDEO_EXTENSIONS = {"mov", "mp4", "m4v"}
AUDIO_EXTENSIONS = {"caf", "m4a", "aac", "amr", "mp3", "wav"}


def message_text(text, attributed_body):
    """Return a message's text, falling back to its attributedBody."""
    if not text:
        text = decode_attributed_body(attributed_body) or ""
    return text.replace(ATTACHMENT_MARKER, "")


def attachment_type(mime_type, name):
    """Classify an attachment as photo, video, audio or file."""
    major = (mime_type or "").split("/")[0]
    if major == "image":
        return "photo"
    if major in ("video", "audio"):
        return major
    extension = name.rsplit(".", 1)[-1].lower() if name and "." in name else ""
    if extension in PHOTO_EXTENSIONS:
        return "photo"
    if extension in VIDEO_EXTENSIONS:
        return "video"
    if extension in AUDIO_EXTENSIONS:
        return "audio"
    return "file"


def get_attachments(cursor, message_ids):
    """
    Map each message id to its attachments' names and types. File contents
    are never read. Returns an empty map if the attachment tables are missing.
    """
    attachments = {}
    ids = list(message_ids)
    for start in range(0, len(ids), 500):  # stay under SQLite's variable limit
        chunk = ids[start:start + 500]
        placeholders = ",".join("?" * len(chunk))
        try:
            cursor.execute(f"""
            SELECT maj.message_id, a.transfer_name, a.filename, a.mime_type
            FROM message_attachment_join maj
            JOIN attachment a ON a.ROWID = maj.attachment_id
            WHERE maj.message_id IN ({placeholders})
            ORDER BY maj.message_id, a.ROWID
            """, chunk)
        except sqlite3.OperationalError:
            return {}
        for message_id, transfer_name, filename, mime_type in cursor.fetchall():
            name = transfer_name or (filename.rsplit("/", 1)[-1] if filename else None)
            attachments.setdefault(message_id, []).append({
                "name": name,
                "type": attachment_type(mime_type, name),
                "mime_type": mime_type,
            })
    return attachments


def describe_attachments(attachments):
    """Placeholder text for a message that is only attachments, e.g. "[photo: IMG_1234.HEIC]"."""
    return " ".join(
        f"[{a['type']}: {a['name']}]" if a["name"] else f"[{a['type']}]" for a in attachments
    )


def is_tapback(associated_message_type):
    """
    True for tapback reactions (Loved, Liked, Laughed at, ...) and their
    removals. Messages stores these as ordinary rows whose text quotes the
    message they react to, with associated_message_type 2000-2999 for a
    reaction and 3000-3999 for removing one.
    """
    return associated_message_type is not None and 2000 <= associated_message_type < 4000


def get_messages_by_phone(phone_number, limit=50, include_groups=False):
    """
    Retrieve messages for a specific phone number or email handle.

    Args:
        phone_number: Handle to query (e.g., "+14155550123")
        limit: Maximum number of messages to retrieve
        include_groups: Also return messages from group chats this contact
            is in. By default only the one-to-one thread is returned.

    Returns:
        List of message dictionaries with time, text, sender info
    """
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # The sender is message.handle_id, not the chat's participant list: joining
    # through chat_handle_join labelled every group message with the queried
    # contact, whoever actually sent it.
    query = """
    SELECT
        m.date,
        m.text,
        m.is_from_me,
        s.id as sender_handle,
        m.ROWID as message_id,
        m.cache_has_attachments,
        m.associated_message_type,
        m.attributedBody,
        (SELECT COUNT(*) FROM chat_handle_join p WHERE p.chat_id = cmj.chat_id) as participants
    FROM message m
    JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
    LEFT JOIN handle s ON m.handle_id = s.ROWID
    WHERE cmj.chat_id IN (
        SELECT chj.chat_id
        FROM chat_handle_join chj
        JOIN handle h ON chj.handle_id = h.ROWID
        WHERE h.id = ?
    )
    AND (? OR (SELECT COUNT(*) FROM chat_handle_join p WHERE p.chat_id = cmj.chat_id) = 1)
    ORDER BY m.date DESC
    LIMIT ?
    """

    cursor.execute(query, (phone_number, include_groups, limit))
    rows = cursor.fetchall()
    attachments_by_message = get_attachments(cursor, [row[4] for row in rows])

    messages = []
    for row in rows:
        # Convert Apple's timestamp (nanoseconds since 2001-01-01) to datetime
        timestamp = row[0] / 1000000000 + 978307200  # Unix timestamp
        dt = datetime.fromtimestamp(timestamp)
        is_group = row[8] > 1
        if row[2]:
            sender = "Me"
        else:
            sender = row[3] or ("Unknown" if is_group else phone_number)
        attachments = attachments_by_message.get(row[4], [])
        text = message_text(row[1], row[7])
        if not text.strip() and attachments:
            text = describe_attachments(attachments)

        messages.append({
            "time": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "text": text,
            "is_from_me": bool(row[2]),
            "sender": sender,
            "message_id": row[4],
            "has_attachments": bool(row[5]) or bool(attachments),
            "attachments": attachments,
            "is_reaction": is_tapback(row[6]),
            "is_group": is_group
        })

    conn.close()
    return messages


def search_messages(search_term, limit=50):
    """
    Search for messages containing a specific term.
    
    Args:
        search_term: Text to search for
        limit: Maximum number of results
    
    Returns:
        List of matching messages with context
    """
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Messages whose text lives only in attributedBody can't be matched in SQL,
    # so fetch them as candidates and match the decoded text in Python.
    query = """
    SELECT
        m.date,
        m.text,
        m.is_from_me,
        s.id as sender_handle,
        m.attributedBody,
        m.associated_message_type
    FROM message m
    LEFT JOIN handle s ON m.handle_id = s.ROWID
    WHERE m.text LIKE ?
       OR ((m.text IS NULL OR m.text = '') AND m.attributedBody IS NOT NULL)
    ORDER BY m.date DESC
    """

    cursor.execute(query, (f"%{search_term}%",))
    needle = search_term.lower()

    messages = []
    for row in cursor:
        text = message_text(row[1], row[4])
        if needle not in text.lower():
            continue
        timestamp = row[0] / 1000000000 + 978307200
        dt = datetime.fromtimestamp(timestamp)

        messages.append({
            "time": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "text": text,
            "is_from_me": bool(row[2]),
            "sender": "Me" if row[2] else (row[3] or "Unknown"),
            "is_reaction": is_tapback(row[5])
        })
        if len(messages) >= limit:
            break

    conn.close()
    return messages


def get_all_contacts():
    """
    Get list of all contacts you've messaged.
    
    Returns:
        List of unique phone numbers/handles
    """
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    query = """
    SELECT DISTINCT h.id
    FROM handle h
    JOIN chat_handle_join chj ON h.ROWID = chj.handle_id
    ORDER BY h.id
    """
    
    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()
    
    return [row[0] for row in rows]


def get_recent_conversations(limit=10):
    """
    Get the most recent conversations with message counts.
    
    Args:
        limit: Number of conversations to retrieve
    
    Returns:
        List of conversation info with contact and message count. A group
        chat is one conversation (contact is its name, or its participants);
        one-to-one chats with the same handle are merged.
    """
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Count per chat, then look up participants. Grouping by participant (as
    # before) counted every group message once for each person in the group.
    cursor.execute("""
    SELECT
        c.ROWID,
        c.display_name,
        COUNT(m.ROWID) as message_count,
        MAX(m.date) as last_message_date
    FROM chat c
    JOIN chat_message_join cmj ON cmj.chat_id = c.ROWID
    JOIN message m ON m.ROWID = cmj.message_id
    GROUP BY c.ROWID
    """)
    chats = cursor.fetchall()

    participants = {}
    cursor.execute("""
    SELECT chj.chat_id, h.id
    FROM chat_handle_join chj
    JOIN handle h ON chj.handle_id = h.ROWID
    ORDER BY h.id
    """)
    for chat_id, handle in cursor.fetchall():
        participants.setdefault(chat_id, []).append(handle)
    conn.close()

    merged = {}
    for chat_id, display_name, count, last_date in chats:
        people = participants.get(chat_id, [])
        is_group = len(people) > 1
        if is_group:
            key = ("chat", chat_id)
            contact = display_name or ", ".join(people)
        else:
            key = ("handle", people[0] if people else chat_id)
            contact = people[0] if people else (display_name or "Unknown")
        entry = merged.setdefault(key, {
            "contact": contact,
            "message_count": 0,
            "last_date": last_date,
            "is_group": is_group,
            "participants": people,
        })
        entry["message_count"] += count
        entry["last_date"] = max(entry["last_date"], last_date)

    conversations = []
    for entry in sorted(merged.values(), key=lambda e: e["last_date"], reverse=True)[:limit]:
        timestamp = entry.pop("last_date") / 1000000000 + 978307200
        dt = datetime.fromtimestamp(timestamp)
        entry["last_message"] = dt.strftime("%Y-%m-%d %H:%M:%S")
        conversations.append(entry)

    return conversations


if __name__ == "__main__":
    # Command-line interface
    include_groups = "--include-groups" in sys.argv
    sys.argv = [arg for arg in sys.argv if arg != "--include-groups"]

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python query_messages.py <phone_number> [limit] [--include-groups]")
        print("  python query_messages.py --search <term> [limit]")
        print("  python query_messages.py --contacts")
        print("  python query_messages.py --recent [limit]")
        sys.exit(1)
    
    if sys.argv[1] == "--contacts":
        contacts = get_all_contacts()
        print(json.dumps(contacts, indent=2))
    
    elif sys.argv[1] == "--recent":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        conversations = get_recent_conversations(limit)
        print(json.dumps(conversations, indent=2))
    
    elif sys.argv[1] == "--search":
        if len(sys.argv) < 3:
            print("Error: Search term required")
            sys.exit(1)
        search_term = sys.argv[2]
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 50
        messages = search_messages(search_term, limit)
        print(json.dumps(messages, indent=2))
    
    else:
        # Get messages by phone number
        phone_number = sys.argv[1]
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 50
        messages = get_messages_by_phone(phone_number, limit, include_groups)
        print(json.dumps(messages, indent=2))
