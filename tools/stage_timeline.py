#!/usr/bin/env python3
"""Stage timeline of a boot from the runtime's stderr log: the title's own state (LEONIDA_PEEK lines) joined with the
scripted presses (LEONIDA_INPUT_SCRIPT), so a Confirm can be paired with the state change it caused.

Reads only the runtime's own lines:
  [rt] peek t=<s>s: 0x7446510=<v> 0x98f828c=<v> [0x7453ed0=<v>] ...
  [rt] gameinput: scripted press of button <b> at <t> s

State meanings for this build: game state 0x7446510 (2 init, 3 running); session = low dword of 0x98f828c
(1 boot screens, 3 landing, 0xd first-run pages, 0 story load); low byte of 0x7453ed0 goes 2 -> 0 when the loading
screen ends.

usage: stage_timeline.py LOG [--json]
"""
import argparse
import json
import re
import sys

PEEK = re.compile(r"\[rt\] peek t=(\d+)s:(.*)")
FIELD = re.compile(r"0x([0-9a-fA-F]+)=([0-9a-fA-F?,]+)")
PRESS = re.compile(r"\[rt\] gameinput: scripted press of button (\d+) at ([0-9.]+) s")

SESSION = {1: "boot screens", 3: "landing", 0xD: "first-run pages", 0: "story load"}
GAME = {0: "not started", 2: "init", 3: "running"}


def first_value(text):
    if text is None or text.startswith("?"):
        return None
    return int(text.split(",")[0], 16)


def read(path):
    peeks, presses = [], []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = PEEK.search(line)
            if m:
                fields = {k.lower(): v for k, v in FIELD.findall(m.group(2))}
                game = first_value(fields.get("7446510"))
                raw = first_value(fields.get("98f828c"))
                session = None if raw is None else raw & 0xFFFFFFFF
                load = first_value(fields.get("7453ed0"))
                peeks.append({"t": int(m.group(1)), "game": game, "session": session, "load": load})
                continue
            m = PRESS.search(line)
            if m:
                presses.append({"t": float(m.group(2)), "button": int(m.group(1))})
    return peeks, presses


def timeline(peeks, presses):
    """Stage changes with the presses between them; each press is paired with the next stage change, if any."""
    events = []
    last = None
    seen_load_byte = False
    for p in peeks:
        load = p["load"]
        ended = p["session"] == 0 and load is not None and seen_load_byte and (load & 0xFF) == 0
        if load is not None and (load & 0xFF) == 2:
            seen_load_byte = True
        name = "story load (loading screen ended)" if ended else (
            SESSION.get(p["session"], f"session {p['session']:#x}") if p["game"] == 3 and p["session"] is not None
            else GAME.get(p["game"], "no title state yet" if p["game"] is None else f"game state {p['game']:#x}"))
        if name != last:
            events.append({"t": p["t"], "stage": name})
            last = name
    for pr in presses:
        nxt = next((e for e in events if e["t"] >= pr["t"]), None)
        pr["next_change"] = None if nxt is None else {"t": nxt["t"], "stage": nxt["stage"]}
    return events


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log")
    ap.add_argument("--json", action="store_true", help="print the stages and presses as JSON")
    a = ap.parse_args()
    peeks, presses = read(a.log)
    if not peeks:
        print("no peek lines: run with LEONIDA_PEEK=0x7446510,0x98f828c,0x7453ed0", file=sys.stderr)
        return 1
    events = timeline(peeks, presses)
    if a.json:
        print(json.dumps({"stages": events, "presses": presses}, indent=1))
        return 0
    print("stages (first peek showing each):")
    for e in events:
        print(f"  {e['t']:>5} s  {e['stage']}")
    print("scripted presses -> next stage change:")
    for pr in presses:
        n = pr["next_change"]
        print(f"  {pr['t']:>7.1f} s  button {pr['button']}  -> " +
              (f"{n['stage']} at {n['t']} s" if n else "no later change"))
    return 0


if __name__ == "__main__":
    try:  # a redirected stdout is strict ANSI code page under -I; write '?' for what it cannot encode
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError, OSError):
        pass
    sys.exit(main())
