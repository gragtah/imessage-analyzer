---
name: imessage-analyzer
description: Analyze and extract information from iMessage conversations on Mac. Use when user wants to read messages, search conversations, extract action items, find URLs/phone numbers/addresses, get conversation statistics, identify questions, or analyze message patterns. Works around broken MCP iMessage implementation by directly querying the Messages SQLite database.
---

# iMessage Analyzer

Comprehensive iMessage analysis toolkit that queries the Messages database directly on Mac.

## Quick Start

### Reading Messages from a Contact

Use `query_messages.py` to retrieve messages:

```bash
# Get messages from a phone number
python3 scripts/query_messages.py "+14155550123" 50

# Output is JSON with all message details
```

### Analyzing a Conversation

Chain query and analysis:

```bash
# Get messages and analyze them
python3 scripts/query_messages.py "+14155550123" 100 | python3 scripts/analyze_messages.py -
```

Analysis extracts:
- URLs and links
- Phone numbers
- Addresses  
- Dates and times mentioned
- Action items and tasks
- Questions asked
- Conversation statistics

### Other Queries

```bash
# List all contacts
python3 scripts/query_messages.py --contacts

# Get recent conversations (group chats appear once, with participants)
python3 scripts/query_messages.py --recent 20

# A contact's one-to-one thread plus the group chats they're in
python3 scripts/query_messages.py "+14155550123" 100 --include-groups

# Search all messages for a term
python3 scripts/query_messages.py --search "dinner" 50
```

## Using These Scripts

The scripts must be executed via osascript's `do shell script` command since they need to access the user's Messages database on their Mac:

```applescript
do shell script "python3 /path/to/scripts/query_messages.py '+14155550123' 50"
```

Or use the Control your Mac:osascript tool:

```javascript
{
  "script": "do shell script \"cd /path/to/skill && python3 scripts/query_messages.py '+14155550123' 50\""
}
```

## Workflow Pattern

When a user asks to analyze iMessage conversations:

1. Identify the contact (use Contacts app via osascript if needed)
2. Get their phone number or email 
3. Query messages using `query_messages.py`
4. Parse the JSON output
5. Optionally pipe to `analyze_messages.py` for extraction
6. Present findings to the user conversationally

## Example Use Cases

**"Summarize my conversation with Alex"**
1. Get Alex's phone number from Contacts
2. Query last 100 messages
3. Analyze for key topics, action items, questions
4. Provide summary to user

**"Find all the links John sent me"**
1. Get John's contact info
2. Query his messages
3. Extract URLs with timestamps
4. List them for the user

**"What questions has Sarah asked me that I haven't answered?"**
1. Query Sarah's conversation
2. Extract all questions from her
3. Check if followed by your responses
4. Report unanswered questions

## Technical Notes

- Messages database: `~/Library/Messages/chat.db`
- Requires Full Disk Access permission for Claude
- Phone numbers in handle table are formatted like "+14155550123"
- Message dates are nanoseconds since 2001-01-01 (Apple epoch)
- Querying a contact returns only your one-to-one thread unless `--include-groups` is passed; each message's `sender` is its actual sender and `is_group` marks group-chat messages
- When `text` is empty, the scripts decode the message from `attributedBody`, where newer macOS versions store it
- Scripts output JSON for easy parsing
