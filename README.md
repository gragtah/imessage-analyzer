# iMessage Analyzer

A Claude skill for reading and analyzing your iMessage conversations on macOS. It queries the local Messages database directly with SQLite, then extracts links, phone numbers, addresses, dates, action items, unanswered questions and conversation stats.

Ask Claude things like:

- "Summarize my conversation with Alex"
- "Find all the links John sent me"
- "What questions has Sarah asked me that I haven't answered?"

## Requirements

- macOS with Messages signed in
- Python 3 (standard library only, no dependencies)
- **Full Disk Access** for whatever runs the scripts (Terminal, or the Claude app), since `~/Library/Messages/chat.db` is protected. Grant it in System Settings → Privacy & Security → Full Disk Access.

## Install

**Claude Code** (as a plugin):

```
/plugin marketplace add gragtah/imessage-analyzer
/plugin install imessage-analyzer@gragtah
```

**Claude apps** (as a skill): zip the `skills/imessage-analyzer` folder and upload it as a skill in Claude's settings.

## Use the scripts directly

```bash
cd skills/imessage-analyzer

# Recent conversations, with message counts
python3 scripts/query_messages.py --recent 20

# Last 100 messages with one contact, analyzed
python3 scripts/query_messages.py "+14155550123" 100 | python3 scripts/analyze_messages.py -

# Same, including group chats that contact is in
python3 scripts/query_messages.py "+14155550123" 100 --include-groups

# Search every conversation
python3 scripts/query_messages.py --search "dinner" 50
```

Both scripts emit JSON.

## Privacy

Everything runs locally against your own Messages database. The scripts make no network calls. When used through Claude, only the messages a query returns are read into the conversation.

## Known limitations

- Newer macOS versions often store a message's text only in `attributedBody`, an archived rich-text blob in an undocumented format. The scripts decode the string payload from it, which covers ordinary messages; anything that doesn't match the expected layout comes back as empty text rather than an error.
- Searching has to decode those messages before matching, so a search for a rare term scans more of the database than a plain SQL query would.
- A contact with several handles (a phone number and an email, say) has a separate thread per handle; query each one.
- Extraction (addresses, dates, action items) uses regex heuristics, so expect some misses and false positives.

## Tests

The tests build a small synthetic `chat.db` (one-to-one chats, a group chat and `attributedBody`-only messages), so they run anywhere without touching real messages:

```bash
python3 -m unittest discover -s tests
```

## Layout

```
.claude-plugin/
  plugin.json          plugin manifest
  marketplace.json     lets this repo be added as a plugin marketplace
skills/imessage-analyzer/
  SKILL.md             instructions Claude follows
  scripts/
    query_messages.py  reads chat.db (contacts, recent chats, search, by handle)
    analyze_messages.py  extracts links, action items, questions, stats
tests/
  test_query_messages.py  runs against a synthetic chat.db
```

## License

MIT
