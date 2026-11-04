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

ALICE = "+14155550101"
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


class GroupStatsTest(unittest.TestCase):
    def setUp(self):
        # Oldest first; the tests also feed this newest first, as query_messages.py does
        self.chronological = [
            msg("10:00", "Dinner Saturday?", BOB, is_group=True),
            msg("10:05", "I'm in", ALICE, is_group=True),
            msg("10:06", "Same", "Me", is_group=True),
            msg("10:20", "Great, 7pm", BOB, is_group=True),
            msg("10:21", "See you then", BOB, is_group=True),
        ]

    def stats(self, messages):
        return am.analyze_conversation(messages)["stats"]

    def test_counts_messages_per_sender(self):
        stats = self.stats(self.chronological)
        self.assertEqual(stats["messages_by_sender"], {BOB: 3, ALICE: 1, "Me": 1})

    def test_response_times_are_per_sender(self):
        # Alice replied 5 min after Bob, I replied 1 min after Alice, Bob 14 min after me.
        # Bob's follow-up to himself isn't a reply.
        stats = self.stats(self.chronological)
        self.assertEqual(
            stats["avg_response_time_by_sender_minutes"], {ALICE: 5.0, "Me": 1.0, BOB: 14.0}
        )

    def test_overall_response_time_still_measures_me_versus_others(self):
        # Me after Alice (1 min) and Bob after me (14 min); Alice after Bob doesn't involve me
        self.assertEqual(self.stats(self.chronological)["avg_response_time_minutes"], 7.5)

    def test_message_order_does_not_matter(self):
        self.assertEqual(self.stats(self.chronological), self.stats(self.chronological[::-1]))


if __name__ == "__main__":
    unittest.main()
