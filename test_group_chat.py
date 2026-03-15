#!/usr/bin/env python3
"""End-to-end group chat test."""
import os, socket, subprocess, time
from brainfuck.interpreter import run as bf_run

def load(name):
    with open(f'brainfuck/{name}', 'r', encoding='utf-8') as f:
        return f.read()

def bf(prog, inp):
    return bf_run(load(prog), inp).strip()

os.system("rm -f server/messages.db")
serverP = subprocess.Popen(
    ["python3", "server/server.py"],
    cwd="/Users/adiprabs/Coding/BF Messaging",
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)
time.sleep(1.5)

try:
    def recv_lines(sock, timeout=0.8):
        sock.setblocking(False)
        end = time.time() + timeout
        buf = b""
        out = []
        while time.time() < end:
            try:
                c = sock.recv(4096)
                if not c: break
                buf += c
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    s = line.decode(errors="replace").strip()
                    if s:
                        out.append(s)
            except BlockingIOError:
                time.sleep(0.02)
        return out

    alice = socket.socket()
    alice.connect(("127.0.0.1", 9999))
    alice.sendall((bf("register_cmd.bf", "alice\n") + "\n").encode())
    time.sleep(0.2)
    ar = recv_lines(alice)
    print(f"Alice registered: {any(x.startswith('+OK') for x in ar)}")

    alice.sendall((bf("create_group_cmd.bf", "devteam\n") + "\n").encode())
    time.sleep(0.2)
    ag = recv_lines(alice)
    print(f"Alice created devteam: {any('+GROUP devteam' in x for x in ag)}")

    bob = socket.socket()
    bob.connect(("127.0.0.1", 9999))
    bob.sendall((bf("register_cmd.bf", "bob\n") + "\n").encode())
    time.sleep(0.2)
    br = recv_lines(bob)
    print(f"Bob registered: {any(x.startswith('+OK') for x in br)}")

    bob.sendall((bf("join_group_cmd.bf", "devteam\n") + "\n").encode())
    time.sleep(0.2)
    bj = recv_lines(bob)
    print(f"Bob joined devteam: {any('Joined group devteam' in x for x in bj)}")

    alice.sendall((bf("send_to_group_cmd.bf", "devteam\nhello group\n") + "\n").encode())
    time.sleep(0.2)
    as_resp = recv_lines(alice)
    print(f"Alice sent to group: {any('Message sent to group' in x for x in as_resp)}")

    time.sleep(0.3)
    bob_incoming = recv_lines(bob)
    print(f"Bob got incoming: {any('+INCOMING GROUP devteam alice' in x for x in bob_incoming)}")

    alice.close()
    bob.close()
    print("\n✓ Group chat test: PASSED")

finally:
    serverP.terminate()
    try:
        serverP.wait(timeout=2)
    except subprocess.TimeoutExpired:
        serverP.kill()
