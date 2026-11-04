"""
Tests for query_messages.py against a small synthetic chat.db.

The fixture mirrors the parts of the macOS Messages schema the scripts read:
one-to-one chats, a group chat, and messages whose text exists only in
attributedBody (as on newer macOS versions). Run from the repo root:

    python3 -m unittest discover -s tests
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "imessage-analyzer" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import query_messages as qm  # noqa: E402

ALICE = "+14155550101"
BOB = "+14155550102"
CAROL = "carol@example.com"

LONG_TEXT = "Reminder: " + "the unicorn parade starts at noon, bring snacks. " * 4


def apple_ns(when):
    """Local datetime string -> nanoseconds since 2001-01-01, as chat.db stores it."""
    seconds = datetime.strptime(when, "%Y-%m-%d %H:%M").timestamp() - 978307200
    return int(seconds * 1_000_000_000)


def typedstream(text):
    """Build an attributedBody blob laid out like the ones macOS writes."""
    payload = text.encode("utf-8")
    n = len(payload)
    if n < 0x80:
        length = bytes([n])
    elif n < 0x10000:
        length = b"\x81" + n.to_bytes(2, "little")
    else:
        length = b"\x82" + n.to_bytes(4, "little")
    return (
        b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x12NSAttributedString\x00"
        b"\x84\x84\x08NSObject\x00\x85\x92\x84\x84\x84\x08NSString\x01\x94\x84\x01+"
        + length
        + payload
        + b"\x86\x84\x02iI\x01\x05\x92\x84\x84\x84\x0cNSDictionary\x00"
    )


def build_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
        CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT, display_name TEXT);
        CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER);
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY, date INTEGER, text TEXT, attributedBody BLOB,
            is_from_me INTEGER, handle_id INTEGER,
            cache_has_attachments INTEGER DEFAULT 0, associated_message_type INTEGER DEFAULT 0
        );
        CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
        CREATE TABLE attachment (
            ROWID INTEGER PRIMARY KEY, filename TEXT, mime_type TEXT, transfer_name TEXT
        );
        CREATE TABLE message_attachment_join (message_id INTEGER, attachment_id INTEGER);
        """
    )
    conn.executemany("INSERT INTO handle VALUES (?, ?)", [(1, ALICE), (2, BOB), (3, CAROL)])
    conn.executemany(
        "INSERT INTO chat VALUES (?, ?, ?)",
        [(1, ALICE, ""), (2, "chat123456", "Weekend plans"), (3, BOB, "")],
    )
    conn.executemany(
        "INSERT INTO chat_handle_join VALUES (?, ?)",
        [(1, 1), (2, 1), (2, 2), (2, 3), (3, 2)],
    )
    # (rowid, chat, date, text, attributedBody, is_from_me, handle_id[, associated_message_type])
    messages = [
        (1, 1, "2026-10-01 10:00", "Are we still on for dinner?", None, 0, 1),
        (2, 1, "2026-10-01 10:05", "Yes, 7pm", None, 1, 1),
        (3, 2, "2026-10-01 11:00", "Dinner at my place Saturday", None, 0, 2),
        (4, 2, "2026-10-01 11:10", None, typedstream("I'll bring dessert 🍰"), 0, 1),
        (5, 2, "2026-10-01 11:20", "Count me in", None, 1, 0),
        (6, 3, "2026-10-01 12:00", None, typedstream(LONG_TEXT), 0, 2),
        (7, 1, "2026-10-01 12:30", None, typedstream("See you at DINNER"), 0, 1),
        (8, 3, "2026-10-01 12:40", "Can you call me?", None, 0, 2),
        (9, 3, "2026-10-01 12:41", "Loved “Can you call me?”", None, 1, 0, 2000),
        # U+FFFC marks where an attachment sits in the text
        (10, 3, "2026-10-01 12:45", "\ufffc", None, 0, 2),
        (11, 3, "2026-10-01 12:50", "\ufffcLook at this menu", None, 0, 2),
        (12, 3, "2026-10-01 12:55", None, typedstream("\ufffc\ufffc"), 1, 0),
    ]
    for rowid, chat, when, text, body, from_me, handle, *rest in messages:
        assoc = rest[0] if rest else 0
        conn.execute(
            "INSERT INTO message (ROWID, date, text, attributedBody, is_from_me, handle_id, "
            "associated_message_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (rowid, apple_ns(when), text, body, from_me, handle, assoc),
        )
        conn.execute("INSERT INTO chat_message_join VALUES (?, ?)", (chat, rowid))
    # (attachment rowid, message rowid, filename, mime_type, transfer_name)
    attachments = [
        (1, 10, "~/Library/Messages/Attachments/ab/IMG_0001.HEIC", "image/heic", "IMG_0001.HEIC"),
        (2, 11, "~/Library/Messages/Attachments/cd/menu.pdf", "application/pdf", "menu.pdf"),
        (3, 12, "~/Library/Messages/Attachments/ef/clip.mov", None, None),
        (4, 12, None, None, None),
    ]
    for rowid, message, filename, mime, name in attachments:
        conn.execute("INSERT INTO attachment VALUES (?, ?, ?, ?)", (rowid, filename, mime, name))
        conn.execute("INSERT INTO message_attachment_join VALUES (?, ?)", (message, rowid))
        conn.execute("UPDATE message SET cache_has_attachments = 1 WHERE ROWID = ?", (message,))
    conn.commit()
    conn.close()


class QueryMessagesTest(unittest.TestCase):
    def setUp(self):
        # A space in the path checks that the read-only URI is quoted properly
        self.tmp = tempfile.TemporaryDirectory(prefix="Messages copy ")
        self.db = os.path.join(self.tmp.name, "chat.db")
        build_db(self.db)
        patcher = mock.patch.object(qm, "get_db_path", return_value=self.db)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_database_is_opened_read_only(self):
        conn = qm.connect()
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM message").fetchone()[0], 12)
        with self.assertRaisesRegex(sqlite3.OperationalError, "readonly"):
            conn.execute("DELETE FROM message")

    def test_contact_lookup_defaults_to_the_one_to_one_thread(self):
        texts = [m["text"] for m in qm.get_messages_by_phone(ALICE, 50)]
        self.assertEqual(texts, ["See you at DINNER", "Yes, 7pm", "Are we still on for dinner?"])

    def test_group_messages_are_attributed_to_their_real_sender(self):
        messages = qm.get_messages_by_phone(ALICE, 50, include_groups=True)
        by_text = {m["text"]: m for m in messages}
        self.assertEqual(by_text["Dinner at my place Saturday"]["sender"], BOB)
        self.assertEqual(by_text["I'll bring dessert 🍰"]["sender"], ALICE)
        self.assertEqual(by_text["Count me in"]["sender"], "Me")
        self.assertTrue(by_text["Count me in"]["is_group"])
        self.assertFalse(by_text["Yes, 7pm"]["is_group"])

    def test_search_returns_each_group_message_once(self):
        results = qm.search_messages("dinner", 50)
        texts = [m["text"] for m in results]
        self.assertEqual(len(texts), len(set(texts)), f"duplicate rows: {texts}")
        self.assertEqual(
            texts,
            ["See you at DINNER", "Dinner at my place Saturday", "Are we still on for dinner?"],
        )
        self.assertEqual(results[1]["sender"], BOB)

    def test_search_finds_text_stored_only_in_attributed_body(self):
        results = qm.search_messages("UNICORN", 50)
        self.assertEqual([m["text"] for m in results], [LONG_TEXT])

    def test_tapback_reactions_are_flagged_in_lookups_and_search(self):
        lookup = {m["text"]: m for m in qm.get_messages_by_phone(BOB, 50)}
        self.assertTrue(lookup["Loved “Can you call me?”"]["is_reaction"])
        self.assertFalse(lookup["Can you call me?"]["is_reaction"])
        found = {m["text"]: m for m in qm.search_messages("call me", 50)}
        self.assertEqual(set(found), {"Can you call me?", "Loved “Can you call me?”"})
        self.assertTrue(found["Loved “Can you call me?”"]["is_reaction"])
        self.assertFalse(found["Can you call me?"]["is_reaction"])

    def test_attachments_are_listed_and_named_in_place_of_blank_text(self):
        by_id = {m["message_id"]: m for m in qm.get_messages_by_phone(BOB, 50)}
        photo = by_id[10]
        self.assertEqual(photo["text"], "[photo: IMG_0001.HEIC]")
        self.assertEqual(
            photo["attachments"],
            [{"name": "IMG_0001.HEIC", "type": "photo", "mime_type": "image/heic"}],
        )
        self.assertTrue(photo["has_attachments"])

    def test_attachment_with_text_keeps_the_text(self):
        by_id = {m["message_id"]: m for m in qm.get_messages_by_phone(BOB, 50)}
        self.assertEqual(by_id[11]["text"], "Look at this menu")
        self.assertEqual(by_id[11]["attachments"][0]["type"], "file")
        self.assertEqual(by_id[8]["attachments"], [])
        self.assertFalse(by_id[8]["has_attachments"])

    def test_attachment_type_falls_back_to_the_file_extension(self):
        by_id = {m["message_id"]: m for m in qm.get_messages_by_phone(BOB, 50)}
        self.assertEqual(by_id[12]["text"], "[video: clip.mov] [file]")

    def test_search_strips_attachment_markers_from_text(self):
        results = qm.search_messages("look at this", 50)
        self.assertEqual([m["text"] for m in results], ["Look at this menu"])

    def test_lookup_works_without_attachment_tables(self):
        conn = sqlite3.connect(self.db)
        conn.executescript("DROP TABLE attachment; DROP TABLE message_attachment_join;")
        conn.close()
        by_id = {m["message_id"]: m for m in qm.get_messages_by_phone(BOB, 50)}
        self.assertEqual(by_id[10]["text"], "")
        self.assertEqual(by_id[10]["attachments"], [])
        self.assertTrue(by_id[10]["has_attachments"])

    def test_recent_conversations_count_a_group_chat_once(self):
        convos = {c["contact"]: c for c in qm.get_recent_conversations(10)}
        self.assertEqual(set(convos), {ALICE, BOB, "Weekend plans"})
        self.assertEqual(convos[ALICE]["message_count"], 3)
        self.assertEqual(convos["Weekend plans"]["message_count"], 3)
        self.assertTrue(convos["Weekend plans"]["is_group"])
        self.assertEqual(sorted(convos["Weekend plans"]["participants"]), sorted([ALICE, BOB, CAROL]))


class DecodeAttributedBodyTest(unittest.TestCase):
    def test_short_text(self):
        self.assertEqual(qm.decode_attributed_body(typedstream("hi there")), "hi there")

    def test_non_ascii_text(self):
        self.assertEqual(qm.decode_attributed_body(typedstream("café 🍰 ok")), "café 🍰 ok")

    def test_text_longer_than_127_bytes_uses_two_byte_length(self):
        self.assertGreater(len(LONG_TEXT.encode()), 127)
        self.assertEqual(qm.decode_attributed_body(typedstream(LONG_TEXT)), LONG_TEXT)

    def test_missing_or_unrecognized_blob_returns_none(self):
        self.assertIsNone(qm.decode_attributed_body(None))
        self.assertIsNone(qm.decode_attributed_body(b""))
        self.assertIsNone(qm.decode_attributed_body(b"not a typedstream"))
        self.assertIsNone(qm.decode_attributed_body(typedstream("truncated")[:-30]))


if __name__ == "__main__":
    unittest.main()
