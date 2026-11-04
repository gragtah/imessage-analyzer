"""
Tests for analyze_messages.py. It works on the JSON that query_messages.py
emits, so these tests build message dictionaries directly.

    python3 -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "imessage-analyzer" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import analyze_messages as am  # noqa: E402

BOB = "+14155550102"


def msg(time, text, sender, **extra):
    m = {
        "time": f"2026-10-01 {time}:00",
        "text": text,
        "is_from_me": sender == "Me",
        "sender": sender,
        "has_attachments": False,
    }
    m.update(extra)
    return m


class ReactionsTest(unittest.TestCase):
    def setUp(self):
        # Newest first, as query_messages.py returns them
        self.messages = [
            msg("10:06", "Loved “Can you call me later?”", "Me", is_reaction=True),
            msg("10:05", "Sure, after 6", "Me"),
            msg("10:00", "Can you call me later?", BOB),
        ]

    def test_reactions_are_left_out_of_extraction(self):
        result = am.analyze_conversation(self.messages)
        self.assertEqual([q["question"] for q in result["questions"]], ["Can you call me later?"])
        self.assertEqual([a["text"] for a in result["action_items"]], ["Can you call me later?"])

    def test_reactions_are_counted_separately(self):
        stats = am.analyze_conversation(self.messages)["stats"]
        self.assertEqual(stats["total_messages"], 2)
        self.assertEqual(stats["my_messages"], 1)
        self.assertEqual(stats["reactions"], 1)


if __name__ == "__main__":
    unittest.main()
