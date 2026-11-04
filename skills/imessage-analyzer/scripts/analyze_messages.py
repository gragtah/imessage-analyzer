#!/usr/bin/env python3
"""
Analyze iMessage conversations for patterns, action items, and summaries.
"""

import json
import sys
from collections import Counter
from datetime import datetime
import re


def extract_urls(messages):
    """Extract all URLs from messages."""
    url_pattern = r'https?://[^\s]+'
    urls = []
    for msg in messages:
        found_urls = re.findall(url_pattern, msg.get('text', ''))
        for url in found_urls:
            urls.append({
                'url': url,
                'from': msg['sender'],
                'time': msg['time']
            })
    return urls


def extract_phone_numbers(messages):
    """Extract phone numbers from messages."""
    phone_pattern = r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b|\(\d{3}\)\s*\d{3}[-.]?\d{4}'
    phones = []
    for msg in messages:
        found_phones = re.findall(phone_pattern, msg.get('text', ''))
        for phone in found_phones:
            phones.append({
                'phone': phone,
                'from': msg['sender'],
                'time': msg['time']
            })
    return phones


def extract_addresses(messages):
    """Extract potential addresses from messages."""
    # Simple heuristic: lines containing street/avenue/road and numbers
    address_pattern = r'\d+\s+[A-Za-z\s]+(Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln)[.,\s]'
    addresses = []
    for msg in messages:
        found_addresses = re.findall(address_pattern, msg.get('text', ''), re.IGNORECASE)
        for addr in found_addresses:
            addresses.append({
                'address': addr.strip(),
                'from': msg['sender'],
                'time': msg['time']
            })
    return addresses


def extract_dates_times(messages):
    """Extract mentioned dates and times from messages."""
    # Common date/time patterns
    patterns = [
        r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}(?:st|nd|rd|th)?\b',
        r'\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b',
        r'\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b',
        r'\b\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\b',
        r'\b(?:tomorrow|today|tonight|this\s+(?:morning|afternoon|evening))\b'
    ]
    
    dates_times = []
    for msg in messages:
        text = msg.get('text', '')
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                dates_times.append({
                    'mention': match,
                    'context': text[:100],
                    'from': msg['sender'],
                    'time': msg['time']
                })
    return dates_times


def identify_action_items(messages):
    """Identify potential action items or tasks in messages."""
    action_keywords = [
        r'\b(?:need to|have to|should|must|will|gonna|going to)\s+\w+',
        r'\b(?:can you|could you|please|would you)\s+\w+',
        r'\b(?:reminder|remember to|don\'t forget)\b',
        r'\b(?:TODO|todo|To do)\b'
    ]
    
    action_items = []
    for msg in messages:
        text = msg.get('text', '')
        for pattern in action_keywords:
            if re.search(pattern, text, re.IGNORECASE):
                action_items.append({
                    'text': text,
                    'from': msg['sender'],
                    'time': msg['time']
                })
                break  # Only add each message once
    
    return action_items


def identify_questions(messages):
    """Identify questions asked in the conversation."""
    questions = []
    for msg in messages:
        text = msg.get('text', '')
        if '?' in text:
            questions.append({
                'question': text,
                'from': msg['sender'],
                'time': msg['time']
            })
    return questions


def get_conversation_stats(messages):
    """Get basic statistics about the conversation."""
    if not messages:
        return {}
    
    total_messages = len(messages)
    my_messages = sum(1 for m in messages if m['is_from_me'])
    their_messages = total_messages - my_messages
    
    # Calculate date range
    dates = [datetime.strptime(m['time'], "%Y-%m-%d %H:%M:%S") for m in messages]
    oldest = min(dates)
    newest = max(dates)
    duration_days = (newest - oldest).days
    
    # Count attachments
    attachments = sum(1 for m in messages if m.get('has_attachments'))

    messages_by_sender = Counter(m['sender'] for m in messages)

    # Response times (rough estimate based on time gaps). Walk the messages
    # oldest first, whatever order they arrived in. A reply is a message that
    # follows someone else's within an hour: overall, between me and anyone
    # else; per sender, from whoever spoke before them.
    ordered = sorted(messages, key=lambda m: m['time'])
    response_times = []
    response_times_by_sender = {}
    for prev_msg, curr_msg in zip(ordered, ordered[1:]):
        prev_time = datetime.strptime(prev_msg['time'], "%Y-%m-%d %H:%M:%S")
        curr_time = datetime.strptime(curr_msg['time'], "%Y-%m-%d %H:%M:%S")
        gap_minutes = (curr_time - prev_time).total_seconds() / 60
        if gap_minutes >= 60:  # Only count if within an hour
            continue
        if prev_msg['is_from_me'] != curr_msg['is_from_me']:
            response_times.append(gap_minutes)
        if prev_msg['sender'] != curr_msg['sender']:
            response_times_by_sender.setdefault(curr_msg['sender'], []).append(gap_minutes)

    avg_response_time = sum(response_times) / len(response_times) if response_times else 0

    return {
        'total_messages': total_messages,
        'my_messages': my_messages,
        'their_messages': their_messages,
        'messages_by_sender': dict(messages_by_sender.most_common()),
        'first_message': oldest.strftime("%Y-%m-%d"),
        'last_message': newest.strftime("%Y-%m-%d"),
        'duration_days': duration_days,
        'attachments': attachments,
        'avg_response_time_minutes': round(avg_response_time, 1),
        'avg_response_time_by_sender_minutes': {
            sender: round(sum(gaps) / len(gaps), 1)
            for sender, gaps in response_times_by_sender.items()
        }
    }


def analyze_conversation(messages):
    """
    Comprehensive analysis of a conversation.
    
    Args:
        messages: List of message dictionaries
    
    Returns:
        Dictionary with analysis results
    """
    # Tapback reactions quote the message they react to, so leaving them in
    # would repeat that message's questions, links and action items.
    content = [m for m in messages if not m.get('is_reaction')]
    stats = get_conversation_stats(content)
    stats['reactions'] = len(messages) - len(content)
    return {
        'stats': stats,
        'urls': extract_urls(content),
        'phone_numbers': extract_phone_numbers(content),
        'addresses': extract_addresses(content),
        'dates_times': extract_dates_times(content),
        'action_items': identify_action_items(content),
        'questions': identify_questions(content)
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_messages.py <messages_json_file>")
        print("Or pipe JSON: cat messages.json | python analyze_messages.py")
        sys.exit(1)
    
    # Read messages from file or stdin
    if sys.argv[1] == "-":
        messages = json.load(sys.stdin)
    else:
        with open(sys.argv[1], 'r') as f:
            messages = json.load(f)
    
    # Perform analysis
    analysis = analyze_conversation(messages)
    
    # Output results
    print(json.dumps(analysis, indent=2))
