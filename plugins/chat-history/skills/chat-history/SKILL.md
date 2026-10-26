---
name: chat-history
description: Search this project's past Claude Code chat history to find a topic, decision, command, file, error or answer from an earlier conversation. Use when the user asks "what did we decide about X", "when did we discuss X", "find where we talked about X", "what was that command/fix/link from before", "search my chat history", or refers to something from a previous session that is not in the current context.
---

# Chat history search

Claude Code stores every session of a project as a JSONL transcript under
`~/.claude/projects/<project-path-with-dashes>/`. The script below searches those
files quickly and prints matches newest first.

Script: `scripts/search_history.py` in this skill's folder. Run it with `python3`.

## Steps

1. **Pick search terms.** Take 1 to 3 distinctive words from the user's request
   (names, error text, tools, file names). Drop filler like "we", "discussed", "about".
2. **Search.**
   ```bash
   python3 <skill-dir>/scripts/search_history.py "kafka retry"
   ```
   All words must appear in the same message. Useful flags:
   - `--any` match any word, `--regex "kafka|kinesis"` for alternatives or exact phrases
   - `--role user` only what the user typed, `--role assistant` only Claude's replies
   - `--since 7` last 7 days, `--limit 40` more results
   - `--all-projects` search every project on this machine
   - `--include-tools` also search commands run and tool output (use for "what command did we run")
   - `--include-subagents` also search delegated subagent work
3. **Widen if thin.** No or few hits: try synonyms, `--any`, fewer words, then
   `--include-tools`, then `--all-projects`. Stop after 3 or 4 tries and say what you searched.
4. **Read context for the best hits.** Use the session id and time from a hit:
   ```bash
   python3 <skill-dir>/scripts/search_history.py --show 51eb76c4 --at 2026-10-26T12:58 -n 4
   ```
5. **Answer in this shape:**
   - **Summary:** 2 to 4 lines that directly answer the question, citing session id and date.
     If sessions disagree, say which is newest.
   - **Matches:** the most relevant 3 to 8 hits as `date, session, who said it, short snippet`.

## Notes

- Hits from the current session include the user's own search request. Ignore those.
- `--list-sessions` gives an overview (date range, message count, first prompt) when the
  user asks "what have we worked on" or does not remember any keyword.
- History only exists on the machine that ran the sessions. A cloud session container
  usually holds only its own transcript, so say so if the user expects older sessions there.
- Transcripts can contain secrets that were pasted into chat. Do not repeat tokens,
  keys or passwords from results; describe them instead.
