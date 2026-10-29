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

# Search every conversation
python3 scripts/query_messages.py --search "dinner" 50
```

Both scripts emit JSON.

## Privacy

Everything runs locally against your own Messages database. The scripts make no network calls. When used through Claude, only the messages a query returns are read into the conversation.

## Known limitations

- On recent macOS versions, some message bodies are stored only in the `attributedBody` column, so `text` can come back empty for them.
- Querying by handle returns messages from every chat that includes that contact, group chats included, and labels non-self messages with the queried handle rather than the actual sender.
- Extraction (addresses, dates, action items) uses regex heuristics, so expect some misses and false positives.

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
```

## License

MIT
