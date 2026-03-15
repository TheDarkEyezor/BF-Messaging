#!/usr/bin/env python3
"""End-to-end group chat test - improved version."""
import os, socket, subprocess, time, sys
from brainfuck.interpreter import run as bf_run

def load(name):
    with open(f'brainfuck/{name}', 'r', encoding='utf-8') as f:
       return f.read()

def bf(prog, inp):
    return bf_run(load(prog), inp).strip()

def find_server_port(timeout=3):
    """Try to find which port the server is listening on."""
    end = time.time() + timeout
    while time.time() < end:
        for port in range(9999, 10020):
            try:
                sock = socket.socket()
                sock.settimeout(0.1)
                sock.connect(("127.0.0.1", port))
                sock.close()
                return port
            except (ConnectionRefusedError, socket.timeout):
                pass
        time.sleep(0.05)
    return None

print("=" * 60)
print("Group Chat E2E Test")
print("=" * 60)

# Clean database
print("\n1. Cleaning database...")
os.system("rm -f server/messages.db")

# Start server
print("2. Starting server subprocess...")
serverP = subprocess.Popen(
    ["python3", "server/server.py"],
    cwd="/Users/adiprabs/Coding/BF Messaging",
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)
print(f"   Server PID: {serverP.pid}")

# Find server port
print("3. Finding server port...")
server_port = find_server_port()
if not server_port:
    print("   ✗ Could not find server port")
    serverP.terminate()
    sys.exit(1)
print(f"   ✓ Server listening on port {server_port}")

try:
    def recv_lines(sock, timeout=0.8):
        sock.setblocking(False)
        end = time.time() + timeout
        buf = b""
        out = []
        while time.time() < end:
            try:
                c = sock.recv(4096)
                if not c:
                    break
                buf += c
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    s = line.decode(errors="replace").strip()
                    if s:
                        out.append(s)
            except BlockingIOError:
                time.sleep(0.02)
        return out

    # Alice registers
    print("\n4. Alice registers...")
    alice = socket.socket()
    alice.connect(("127.0.0.1", server_port))
    cmd = bf("register_cmd.bf", "alice\n")
    alice.sendall((cmd + "\n").encode())
    time.sleep(0.2)
    ar = recv_lines(alice)
    alice_ok = any(x.startswith('+OK') for x in ar)
    print(f"   Alice registered: {alice_ok}")
    print(f"   Response: {ar}")
    if not alice_ok:
        print("   ✗ Registration failed")
        sys.exit(1)

    # Alice creates group
    print("\n5. Alice creates group...")
    cmd = bf("create_group_cmd.bf", "devteam\n")
    alice.sendall((cmd + "\n").encode())
    time.sleep(0.2)
    ag = recv_lines(alice)
    group_ok = any('+GROUP devteam' in x for x in ag)
    print(f"   Created group: {group_ok}")
    print(f"   Response: {ag}")

    # Bob registers
    print("\n6. Bob registers...")
    bob = socket.socket()
    bob.connect(("127.0.0.1", server_port))
    cmd = bf("register_cmd.bf", "bob\n")
    bob.sendall((cmd + "\n").encode())
    time.sleep(0.2)
    br = recv_lines(bob)
    bob_ok = any(x.startswith('+OK') for x in br)
    print(f"   Bob registered: {bob_ok}")
    print(f"   Response: {br}")

    # Bob joins group
    print("\n7. Bob joins group...")
    cmd = bf("join_group_cmd.bf", "devteam\n")
    bob.sendall((cmd + "\n").encode())
    time.sleep(0.2)
    bj = recv_lines(bob)
    join_ok = any('devteam' in x for x in bj) or any(x.startswith('+OK') for x in bj)
    print(f"   Bob joined: {join_ok}")
    print(f"   Response: {bj}")

    # Alice sends to group
    print("\n8. Alice sends message to group...")
    cmd = bf("send_to_group_cmd.bf", "devteam\nhello group\n")
    print(f"   Command: {repr(cmd)}")
    alice.sendall((cmd + "\n").encode())
    time.sleep(0.2)
    as_resp = recv_lines(alice)
    send_ok = any(x.startswith('+OK') for x in as_resp)
    print(f"   Sent: {send_ok}")
    print(f"   Response: {as_resp}")

    # Check if Bob receives the message
    print("\n9. Checking Bob for incoming message...")
    time.sleep(0.3)
    bob_incoming = recv_lines(bob)
    group_msg_ok = any('+INCOMING GROUP' in x for x in bob_incoming)
    print(f"   Bob received: {group_msg_ok}")
    print(f"   Response: {bob_incoming}")

    alice.close()
    bob.close()
    
    if alice_ok and group_ok and bob_ok and join_ok and send_ok and group_msg_ok:
        print("\n" + "=" * 60)
        print("✓ Group chat test: PASSED")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("✗ Group chat test: FAILED")
        print("=" * 60)
        sys.exit(1)

finally:
    serverP.terminate()
    try:
        serverP.wait(timeout=2)
    except subprocess.TimeoutExpired:
        serverP.kill()
