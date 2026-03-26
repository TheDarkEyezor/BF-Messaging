#!/usr/bin/env python3
"""Debug test runner - more verbose output."""
import os
import socket
import subprocess
import time
import sys

# Change to workspace directory
os.chdir("/Users/adiprabs/Coding/BF Messaging")
sys.path.insert(0, ".")

from brainfuck.interpreter import run as bf_run

def load(name):
    with open(f'brainfuck/{name}', 'r', encoding='utf-8') as f:
        return f.read()

def bf(prog, inp):
    result = bf_run(load(prog), inp).strip()
    print(f"  BF({prog}, {repr(inp)}) → {repr(result)}")
    return result

print("=" * 60)
print("Debug Test: BF Messaging Group Chat")
print("=" * 60)

# Clean database
print("\n1. Cleaning database...")
os.system("rm -f server/messages.db")
print("   ✓ Database deleted")

# Start server
print("\n2. Starting server subprocess...")
try:
    serverP = subprocess.Popen(
        ["python3", "server/server.py"],
        cwd="/Users/adiprabs/Coding/BF Messaging",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    print(f"   ✓ Server process started (PID {serverP.pid})")
except Exception as e:
    print(f"   ✗ Failed to start server: {e}")
    sys.exit(1)

# Wait for server to start
print("\n3. Waiting for server to initialize...")
time.sleep(2)

# Check if server is still alive
if serverP.poll() is not None:
    stdout, stderr = serverP.communicate()
    print(f"   ✗ Server exited early!")
    print(f"   STDOUT: {stdout}")
    print(f"   STDERR: {stderr}")
    sys.exit(1)

print("   ✓ Server appears to be running")

# Try to connect
print("\n4. Testing basic connection...")
try:
    test_sock = socket.socket()
    test_sock.connect(("127.0.0.1", 9999))
    test_sock.close()
    print("   ✓ Successfully connected to port 9999")
except Exception as e:
    print(f"   ✗ Failed to connect: {e}")
    serverP.terminate()
    sys.exit(1)

# Test REGISTER command
print("\n5. Testing REGISTER command...")
try:
    register_cmd = bf("register_cmd.bf", "alice\n")
    print(f"   Register command: {repr(register_cmd)}")
    sock = socket.socket()
    sock.settimeout(2.0)
    sock.connect(("127.0.0.1", 9999))
    print(f"   ✓ Connected to server")
    
    # Send command
    sock.sendall((register_cmd + "\n").encode())
    print(f"   ✓ Sent command: {repr(register_cmd)}")
    
    # Try to receive response
    try:
        resp = sock.recv(4096)
        print(f"   Response: {repr(resp)}")
        if resp:
            print(f"   ✓ Received {len(resp)} bytes")
        else:
            print(f"   ✗ Received empty response (server closed connection)")
    except socket.timeout:
        print(f"   ✗ Socket timeout waiting for response")
    finally:
        sock.close()
        
except Exception as e:
    print(f"   ✗ Error: {e}")
    import traceback
    traceback.print_exc()

# Clean up
print("\n6. Cleaning up...")
serverP.terminate()
try:
    serverP.wait(timeout=2)
    print("   ✓ Server process terminated")
except subprocess.TimeoutExpired:
    serverP.kill()
    print("   ✓ Server process killed")

print("\nDone!")
