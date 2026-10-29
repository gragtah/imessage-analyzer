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


def message_text(text, attributed_body):
    """Return a message's text, falling back to its attributedBody."""
    if text:
        return text
    return decode_attributed_body(attributed_body) or ""


def get_messages_by_phone(phone_number, limit=50):
    """
    Retrieve messages for a specific phone number.
    
    Args:
        phone_number: Phone number to query (e.g., "+14155550123")
        limit: Maximum number of messages to retrieve
    
    Returns:
        List of message dictionaries with time, text, sender info
    """
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    query = """
    SELECT 
        m.date,
        m.text,
        m.is_from_me,
        h.id as handle_id,
        m.ROWID as message_id,
        m.cache_has_attachments,
        m.associated_message_type,
        m.attributedBody
    FROM message m
    JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
    JOIN chat c ON cmj.chat_id = c.ROWID
    JOIN chat_handle_join chj ON c.ROWID = chj.chat_id
    JOIN handle h ON chj.handle_id = h.ROWID
    WHERE h.id = ?
    ORDER BY m.date DESC
    LIMIT ?
    """
    
    cursor.execute(query, (phone_number, limit))
    rows = cursor.fetchall()
    
    messages = []
    for row in rows:
        # Convert Apple's timestamp (nanoseconds since 2001-01-01) to datetime
        timestamp = row[0] / 1000000000 + 978307200  # Unix timestamp
        dt = datetime.fromtimestamp(timestamp)
        
        messages.append({
            "time": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "text": message_text(row[1], row[7]),
            "is_from_me": bool(row[2]),
            "sender": "Me" if row[2] else row[3],
            "message_id": row[4],
            "has_attachments": bool(row[5]),
            "is_reaction": bool(row[6])  # reactions like thumbs up
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
        h.id as handle_id,
        m.attributedBody
    FROM message m
    JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
    JOIN chat c ON cmj.chat_id = c.ROWID
    JOIN chat_handle_join chj ON c.ROWID = chj.chat_id
    JOIN handle h ON chj.handle_id = h.ROWID
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
            "sender": "Me" if row[2] else row[3]
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
        List of conversation info with contact and message count
    """
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    query = """
    SELECT 
        h.id as contact,
        COUNT(m.ROWID) as message_count,
        MAX(m.date) as last_message_date
    FROM message m
    JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
    JOIN chat c ON cmj.chat_id = c.ROWID
    JOIN chat_handle_join chj ON c.ROWID = chj.chat_id
    JOIN handle h ON chj.handle_id = h.ROWID
    GROUP BY h.id
    ORDER BY last_message_date DESC
    LIMIT ?
    """
    
    cursor.execute(query, (limit,))
    rows = cursor.fetchall()
    
    conversations = []
    for row in rows:
        timestamp = row[2] / 1000000000 + 978307200
        dt = datetime.fromtimestamp(timestamp)
        
        conversations.append({
            "contact": row[0],
            "message_count": row[1],
            "last_message": dt.strftime("%Y-%m-%d %H:%M:%S")
        })
    
    conn.close()
    return conversations


if __name__ == "__main__":
    # Command-line interface
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python query_messages.py <phone_number> [limit]")
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
        messages = get_messages_by_phone(phone_number, limit)
        print(json.dumps(messages, indent=2))
