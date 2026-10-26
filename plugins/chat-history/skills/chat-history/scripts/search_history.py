#!/usr/bin/env python3
"""Search Claude Code chat history (the JSONL transcripts in ~/.claude/projects).

Claude Code saves every session as <session-id>.jsonl in a folder named after
the project's working directory (/home/me/app -> -home-me-app). This script
searches the user's prompts and Claude's replies in those files.

Usage:
  search_history.py "kafka retry"              # all words must appear (AND)
  search_history.py "kafka|kinesis" --regex    # regular expression
  search_history.py "redis cache" --any        # any word may appear (OR)
  search_history.py "deploy" --role user       # only what the user typed
  search_history.py "deploy" --since 7         # last 7 days only
  search_history.py "deploy" --all-projects    # every project, not just this one
  search_history.py --list-sessions            # sessions with date and first prompt
  search_history.py --show 51eb76c4 --at 2026-10-26T12:58 -n 4
                                               # messages around a hit

Output is plain text, newest first. Tool calls, tool output, thinking and
system reminders are skipped unless --include-tools is passed.
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")

# User-role messages that start with these were injected by Claude Code, not typed.
INJECTED_PREFIXES = ("<task-notification>", "<agent-message", "<system-reminder",
                     "<command-", "<local-command", "Caveat:")
REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


def project_dir_for(cwd):
    """Claude Code names a project folder after its path, non-alphanumerics -> '-'."""
    return os.path.join(PROJECTS_DIR, re.sub(r"[^A-Za-z0-9]", "-", cwd))


def find_project_dir(cwd):
    """Folder for cwd, or for the nearest parent that has one (sessions started higher up)."""
    path = os.path.abspath(cwd)
    while True:
        d = project_dir_for(path)
        if os.path.isdir(d):
            return d
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def transcript_files(project_dirs, include_subagents):
    files = []
    for d in project_dirs:
        files += glob.glob(os.path.join(d, "*.jsonl"))
        if include_subagents:
            files += glob.glob(os.path.join(d, "*", "subagents", "*.jsonl"))
    return files


def message_text(entry, include_tools):
    """Readable text of one transcript entry, or '' if it has none worth searching."""
    if entry.get("type") not in ("user", "assistant") or entry.get("isMeta"):
        return ""
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        if entry["type"] == "user" and content.lstrip().startswith(INJECTED_PREFIXES):
            return ""
        return REMINDER_RE.sub("", content).strip()
    parts = []
    for block in content or []:
        kind = block.get("type")
        if kind == "text":
            parts.append(block.get("text", ""))
        elif include_tools and kind == "tool_use":
            parts.append(f"[tool {block.get('name')}] {json.dumps(block.get('input'))[:2000]}")
        elif include_tools and kind == "tool_result":
            out = block.get("content")
            if isinstance(out, list):
                out = " ".join(b.get("text", "") for b in out if isinstance(b, dict))
            parts.append(f"[tool output] {str(out)[:2000]}")
    return REMINDER_RE.sub("", "\n".join(parts)).strip()


def parse_ts(ts):
    try:
        return datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def load_session(path, include_tools, need_any=()):
    """Yield (timestamp, role, text) for each searchable message in a transcript.

    need_any: skip raw lines that contain none of these lowercase words, so only
    candidate lines are JSON-decoded.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if need_any and not any(w in line.lower() for w in need_any):
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                text = message_text(entry, include_tools)
                if text:
                    yield entry.get("timestamp", ""), entry["type"], text
    except OSError:
        return


def session_label(path):
    """Short session id plus the project folder it came from."""
    sid = os.path.basename(path).split(".")[0]
    if "subagents" in path:
        sid = f"{path.split(os.sep)[-3][:8]}/{sid}"
    project = os.path.basename(os.path.dirname(path) if "subagents" not in path
                               else os.path.dirname(os.path.dirname(os.path.dirname(path))))
    return sid[:8] if "subagents" not in path else sid, project


def build_matcher(query, use_regex, any_word):
    if use_regex:
        rx = re.compile(query, re.I)
        return (lambda text: bool(rx.search(text))), rx
    words = [w for w in query.lower().split() if w]
    rx = re.compile("|".join(re.escape(w) for w in words), re.I)
    if any_word:
        return (lambda text: any(w in text.lower() for w in words)), rx
    return (lambda text: all(w in text.lower() for w in words)), rx


def snippet(text, rx, width):
    """Text around the first match, with every match wrapped in >>> <<<."""
    m = rx.search(text)
    start = max(0, (m.start() if m else 0) - width // 2)
    piece = text[start:start + width].replace("\n", " ")
    piece = rx.sub(lambda x: f">>>{x.group(0)}<<<", piece)
    return ("..." if start else "") + piece + ("..." if start + width < len(text) else "")


def cmd_search(args, files):
    match, rx = build_matcher(args.query, args.regex, args.any)
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.since) if args.since else None
    # Raw-line prefilter before JSON decoding keeps big histories fast. Words with
    # quotes or backslashes are escaped in JSON, so those skip the prefilter.
    words = [] if args.regex else [w for w in args.query.lower().split() if w]
    pre_words = () if any('"' in w or "\\" in w for w in words) else tuple(words)
    hits = []
    for path in files:
        sid, project = session_label(path)
        for ts, role, text in load_session(path, args.include_tools, pre_words):
            if args.role != "any" and role != args.role:
                continue
            when = parse_ts(ts)
            if cutoff and when and when < cutoff:
                continue
            if match(text):
                hits.append((ts, sid, project, role, text))
    hits.sort(key=lambda h: h[0], reverse=True)

    if not hits:
        print(f"No matches for {args.query!r} in {len(files)} transcript(s).")
        return 0
    sessions = {}
    for h in hits:
        sessions[h[1]] = sessions.get(h[1], 0) + 1
    print(f"{len(hits)} match(es) for {args.query!r} in {len(sessions)} session(s) "
          f"({len(files)} transcript(s) searched). Newest first, showing {min(args.limit, len(hits))}.\n")
    for ts, sid, project, role, text in hits[:args.limit]:
        where = f"{project}  " if args.all_projects else ""
        print(f"[{ts[:16].replace('T', ' ')}] {where}session {sid}  {role}")
        print(f"  {snippet(text, rx, args.context)}\n")
    return 0


def cmd_list(files):
    rows = []
    for path in files:
        first, count, start, end = "", 0, "", ""
        for ts, role, text in load_session(path, False):
            count += 1
            start = start or ts
            end = ts or end
            if not first and role == "user":
                first = text.replace("\n", " ")[:80]
        if count:
            rows.append((end, start, session_label(path)[0], count, first))
    rows.sort(reverse=True)
    print(f"{len(rows)} session(s), most recent first:\n")
    for end, start, sid, count, first in rows:
        print(f"  {sid}  {start[:16].replace('T', ' ')} -> {end[:16].replace('T', ' ')}  {count:>4} msgs  {first!r}")
    return 0


def cmd_show(args, files):
    matches = [p for p in files if os.path.basename(p).startswith(args.show)]
    if not matches:
        print(f"No session starting with {args.show!r}.")
        return 1
    messages = list(load_session(matches[0], args.include_tools))
    # Centre on the first message at or after --at, else show the start.
    idx = next((i for i, m in enumerate(messages) if m[0] >= (args.at or "")), 0)
    lo, hi = max(0, idx - args.n), min(len(messages), idx + args.n + 1)
    print(f"Session {args.show}, messages {lo + 1}-{hi} of {len(messages)}:\n")
    for ts, role, text in messages[lo:hi]:
        body = text if len(text) <= args.max_chars else text[:args.max_chars] + " ...[truncated]"
        print(f"--- [{ts[:16].replace('T', ' ')}] {role}\n{body}\n")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("query", nargs="?", help="words to find (all must appear unless --any)")
    p.add_argument("--regex", action="store_true", help="treat query as a regular expression")
    p.add_argument("--any", action="store_true", help="match any word instead of all")
    p.add_argument("--role", choices=["user", "assistant", "any"], default="any")
    p.add_argument("--since", type=int, help="only the last N days")
    p.add_argument("--limit", type=int, default=20, help="max matches to print (default 20)")
    p.add_argument("--context", type=int, default=240, help="snippet width in characters")
    p.add_argument("--project", default=os.getcwd(), help="project path (default: current dir)")
    p.add_argument("--all-projects", action="store_true", help="search every project")
    p.add_argument("--include-subagents", action="store_true", help="also search subagent transcripts")
    p.add_argument("--include-tools", action="store_true", help="also search tool calls and tool output")
    p.add_argument("--list-sessions", action="store_true", help="list sessions instead of searching")
    p.add_argument("--show", metavar="SESSION", help="print messages from a session (id prefix)")
    p.add_argument("--at", help="with --show: centre on this timestamp, e.g. 2026-10-26T12:58")
    p.add_argument("-n", type=int, default=3, help="with --show: messages before and after")
    p.add_argument("--max-chars", type=int, default=1500, help="with --show: truncate long messages")
    args = p.parse_args()

    if args.all_projects:
        dirs = sorted(glob.glob(os.path.join(PROJECTS_DIR, "*")))
    else:
        d = find_project_dir(args.project)
        if not d:
            print(f"No chat history for {args.project} in {PROJECTS_DIR}. Try --all-projects.")
            return 1
        dirs = [d]
    files = transcript_files(dirs, args.include_subagents)
    if not files:
        print(f"No transcripts found in {', '.join(dirs)}.")
        return 1

    if args.list_sessions:
        return cmd_list(files)
    if args.show:
        return cmd_show(args, files)
    if not args.query:
        p.error("give a query, --list-sessions, or --show SESSION")
    return cmd_search(args, files)


if __name__ == "__main__":
    sys.exit(main())
