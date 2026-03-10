"""End-to-end smoke test for BF Messaging."""
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from brainfuck.interpreter import run as bf_run


def load(prog):
    with open(f"brainfuck/{prog}") as f:
        return f.read()


def bf(prog, inp):
    return bf_run(load(prog), inp).strip()


def session(label, cmds_with_delays):
    s = socket.socket()
    s.connect(("127.0.0.1", 9999))
    f = s.makefile("r")
    responses = []
    for c, delay in cmds_with_delays:
        s.sendall((c + "\n").encode())
        time.sleep(delay)
    s.settimeout(1.0)
    try:
        while True:
            line = f.readline()
            if not line:
                break
            responses.append(line.rstrip("\n"))
    except Exception:
        pass
    s.close()
    print(f"{label}:")
    for r in responses:
        print(f"  {r}")
    return responses


# Register Bob first
bob_resp = session(
    "Bob",
    [
        (bf("register_cmd.bf", "bob\n"), 0.2),
        (bf("quit_cmd.bf", ""), 0.1),
    ],
)

# Alice registers, finds bob, sends message, views history, quits
alice_cmds = [
    (bf("register_cmd.bf", "alice\n"), 0.25),
    (bf("find_cmd.bf", "bob\n"), 0.25),
    (bf("send_cmd.bf", "bob\nhello bob!\n"), 0.25),
    (bf("history_cmd.bf", "bob\n"), 0.5),
    (bf("quit_cmd.bf", ""), 0.1),
]
alice_resp = session("Alice", alice_cmds)

# Assertions
assert any("+OK" in r for r in bob_resp), "Bob registration failed"
assert any("+USER bob" in r for r in alice_resp), "FIND failed"
assert any("+OK Message delivered" in r for r in alice_resp), "SEND failed"
assert any("+HIST" in r for r in alice_resp), "HISTORY failed"
assert any("+END" in r for r in alice_resp), "HISTORY END missing"
print("\nAll assertions passed.")
