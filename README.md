# calude-history-browser

This skill browses any project's chat history on demand within your Claude environment.

It is a Claude Code plugin with one skill, `chat-history`, that searches your past
Claude Code conversations for a topic, decision, command or answer.

Ask things like:

- "What did we decide about the Kafka retry policy?"
- "Find where we discussed the Redis cache."
- "What command did we use to deploy last week?"
- "Search my chat history for the login bug."

Claude picks keywords, runs the search script, reads the best matches in context
and answers with a short summary plus the matching snippets (date, session, who
said it).

## Install

```
/plugin marketplace add sumanoj/calude-history-browser
/plugin install chat-history@claude-chat-history
```

Restart Claude Code (or start a new session) so the skill loads.

## How it works

Claude Code saves every session as a JSONL transcript in
`~/.claude/projects/<project-path-with-dashes>/<session-id>.jsonl`. The script
`plugins/chat-history/skills/chat-history/scripts/search_history.py` reads those
files directly. It uses only the Python standard library and needs no index.

It searches the user's prompts and Claude's replies. Tool calls, tool output,
thinking and system reminders are skipped unless `--include-tools` is passed.
A raw-text prefilter skips non-matching lines before JSON decoding, so about
66 MB of history searches in roughly a second.

## Running the script yourself

```bash
S=plugins/chat-history/skills/chat-history/scripts/search_history.py
python3 $S "kafka retry"                 # all words in one message
python3 $S "kafka|kinesis" --regex       # regular expression
python3 $S "redis cache" --any           # any word
python3 $S "deploy" --role user --since 7
python3 $S "deploy" --all-projects --include-tools
python3 $S --list-sessions
python3 $S --show 51eb76c4 --at 2026-10-26T12:58 -n 4
```

## Where history exists

- **Local CLI:** every past session of every project on that machine.
- **Cloud sessions (claude.ai/code):** each session runs in a fresh container,
  so usually only the current session's transcript is there.

Transcripts can contain anything pasted into chat, including secrets. The skill
tells Claude not to repeat tokens or passwords found in results.
