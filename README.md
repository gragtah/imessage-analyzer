# iMessage Analyzer

A Claude skill for reading and analyzing your iMessage conversations on macOS. It queries the local Messages database directly with SQLite, then extracts links, phone numbers, addresses, dates, action items, unanswered questions and conversation stats.

Ask Claude things like:

- "Summarize my conversation with Alex"
- "Find all the links John sent me"
- "What questions has Sarah asked me that I haven't answered?"

## Requirements

- macOS with Messages signed in
- Python 3 (standard library only, no dependencies)
- Optional: [`pytypedstream`](https://pypi.org/project/pytypedstream/) (`python3 -m pip install pytypedstream`), a full parser for the format newer macOS versions store message text in. The scripts use it when it's installed and a built-in decoder otherwise.
- **Full Disk Access** for the app that runs the scripts, since `~/Library/Messages/chat.db` is protected. That's Terminal, iTerm or your editor if you use its built-in terminal, or the Claude app. Grant it in System Settings → Privacy & Security → Full Disk Access, then quit and reopen that app; until you do, the scripts fail with `authorization denied`.

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

Everything runs locally against your own Messages database, which the scripts open read-only. They make no network calls. When used through Claude, only the messages a query returns are read into the conversation.

## Known limitations

- Newer macOS versions often store a message's text only in `attributedBody`, an archived rich-text blob in Apple's undocumented typedstream format. The scripts read it with `pytypedstream` if it's installed, and otherwise with a built-in decoder that finds the text without fully parsing the archive. The two agreed on every real message body tested, but the built-in one can misread an archive that isn't a message body. Anything neither can read comes back as empty text rather than an error.
- Search can't match messages stored only in `attributedBody` in SQL, so it reads each of them in Python, using the fast built-in decoder to rule out non-matches first. That's quick (about 0.2 seconds for 100,000 such messages in testing), but search time still grows with the size of your history.
- A contact with several handles (a phone number and an email, say) has a separate thread per handle; query each one.
- Contacts appear as phone numbers or emails, not names. The scripts don't read the Contacts app.
- Edited and unsent messages are flagged (`is_edited`, `is_unsent`) on macOS Ventura and later, but earlier versions of an edited message aren't shown.
- Attachments are described by name and type only, never opened. Contact lookups list them (and describe an attachment-only message as, say, `[photo: IMG_1234.HEIC]`), but search results don't.
- Extraction (addresses, dates, action items) uses regex heuristics, so expect some misses and false positives.

## Tests

The tests build a small synthetic `chat.db` (one-to-one chats, a group chat, `attributedBody`-only messages, tapback reactions, attachments, and edited and unsent messages) and sample conversations for the analyzer, so they run anywhere without touching real messages:

```bash
python3 -m unittest discover -s tests
```

The decoder tests run against both decoders. The `pytypedstream` ones are skipped when it isn't installed.

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
  test_query_messages.py    runs against a synthetic chat.db
  test_analyze_messages.py  runs on sample conversations
```

## License

MIT
