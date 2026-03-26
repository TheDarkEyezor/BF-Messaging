#!/usr/bin/env python3
"""Debug test runner - captures server output."""
import os
import socket
import subprocess
import time
import sys
import threading

os.chdir("/Users/adiprabs/Coding/BF Messaging")
sys.path.insert(0, ".")

print("=" * 60)
print("Debug Test: Server Output Capture")
print("=" * 60)

# Clean database
print("\n1. Cleaning database...")
os.system("rm -f server/messages.db")

# Start server and capture output
print("\n2. Starting server...")
serverP = subprocess.Popen(
    ["python3", "server/server.py"],
    cwd="/Users/adiprabs/Coding/BF Messaging",
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1
)

# Read output in background thread
def print_server_output():
    for line in serverP.stdout:
        print(f"   [SERVER] {line.rstrip()}")

output_thread = threading.Thread(target=print_server_output, daemon=True)
output_thread.start()

time.sleep(2)

# Check if server is alive
if serverP.poll() is not None:
    print("   ✗ Server exited with code:", serverP.returncode)
    sys.exit(1)

print("   ✓ Server running (PID", serverP.pid, ")")

# Try a simple connection
print("\n3. Testing connection...")
try:
    sock = socket.socket()
    sock.settimeout(1.0)
    sock.connect(("127.0.0.1", 9999))
    print("   ✓ Connected")
    
    # Send REGISTER
    sock.sendall(b"REGISTER testuser\n")
    print("   ✓ Sent: REGISTER testuser")
    
    # Read response
    try:
        resp = sock.recv(4096)
        print(f"   Response: {repr(resp)}")
    except socket.timeout:
        print("   ✗ No response (timeout)")
    
    sock.close()
except Exception as e:
    print(f"   ✗ Connection failed: {e}")

time.sleep(1)

# Kill server
print("\n4. Terminating server...")
serverP.terminate()
serverP.wait(timeout=2)
print("   ✓ Done")
