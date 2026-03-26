#!/usr/bin/env python3
"""Test that an already-connected user receives a +NEW_GROUP push notification
when they are added to a group by another user.

Regression test for: group created by one user not appearing for already
logged-in members until they reconnect.
"""
import os
import socket
import subprocess
import time
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from brainfuck.interpreter import run as bf_run


def load(name):
    with open(f"brainfuck/{name}", encoding="utf-8") as f:
        return f.read()


def bf(prog, inp):
    return bf_run(load(prog), inp).strip()


def recv_lines(sock, timeout=0.8):
    sock.setblocking(False)
    end = time.time() + timeout
    buf = b""
    out = []
    while time.time() < end:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                s = line.decode(errors="replace").strip()
                if s:
                    out.append(s)
        except BlockingIOError:
            time.sleep(0.02)
    return out


os.system("rm -f server/messages.db")
serverP = subprocess.Popen(
    ["python3", "server/server.py"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
time.sleep(1.5)

try:
    # --- adiprabs registers and creates a group ---
    adiprabs = socket.socket()
    adiprabs.connect(("127.0.0.1", 9999))
    adiprabs.sendall((bf("register_cmd.bf", "adiprabs\n") + "\n").encode())
    time.sleep(0.2)
    r = recv_lines(adiprabs)
    assert any("+OK" in x for x in r), "adiprabs registration failed"

    # --- bob is already logged in before the group is created ---
    bob = socket.socket()
    bob.connect(("127.0.0.1", 9999))
    bob.sendall((bf("register_cmd.bf", "bob\n") + "\n").encode())
    time.sleep(0.2)
    r = recv_lines(bob)
    assert any("+OK" in x for x in r), "bob registration failed"

    # --- adiprabs creates the group ---
    adiprabs.sendall((bf("create_group_cmd.bf", "devteam\n") + "\n").encode())
    time.sleep(0.2)
    r = recv_lines(adiprabs)
    assert any("+GROUP devteam" in x for x in r), "group creation failed"

    # --- adiprabs adds bob (who is still connected) ---
    adiprabs.sendall(b"ADD MEMBER devteam bob\n")
    time.sleep(0.4)
    r = recv_lines(adiprabs)
    assert any("+OK Added bob" in x for x in r), "ADD MEMBER failed"

    # --- bob should have received a +NEW_GROUP push, not need to reconnect ---
    bob_lines = recv_lines(bob, timeout=0.8)
    got_push = any("+NEW_GROUP devteam" in x for x in bob_lines)
    assert got_push, (
        f"bob (already connected) should receive +NEW_GROUP push but got: {bob_lines}"
    )

    # --- alice logs on AFTER group creation – should see it via LIST GROUPS ---
    alice = socket.socket()
    alice.connect(("127.0.0.1", 9999))
    alice.sendall((bf("register_cmd.bf", "alice\n") + "\n").encode())
    time.sleep(0.2)
    recv_lines(alice)

    adiprabs.sendall(b"ADD MEMBER devteam alice\n")
    time.sleep(0.4)
    recv_lines(adiprabs)  # consume +OK

    alice.sendall((bf("list_groups_cmd.bf", "") + "\n").encode())
    time.sleep(0.4)
    alice_lines = recv_lines(alice, timeout=0.8)
    assert any("+GROUP devteam" in x for x in alice_lines), (
        f"alice should see devteam in LIST GROUPS but got: {alice_lines}"
    )

    adiprabs.close()
    bob.close()
    alice.close()
    print("\n✓ new-group-push test: PASSED")

finally:
    serverP.terminate()
    try:
        serverP.wait(timeout=2)
    except subprocess.TimeoutExpired:
        serverP.kill()
