#!/usr/bin/env python3
"""Debug version of server with explicit print statements."""

import asyncio
import sqlite3
import datetime
import os
import sys
import io

# Force unbuffered output
#sys.stdout = io.TextIOWrapper(sys.stdout.buffer, write_through=True)

print("Server starting up...", flush=True)

HOST = "0.0.0.0"
DEFAULT_PORT = 9999
MAX_PORT_TRIES = 20
DB_PATH = os.path.join(os.path.dirname(__file__), "server/messages.db")

print(f"DB_PATH: {DB_PATH}", flush=True)

connected_clients = {}
group_subscribers = {}

_db_conn = None

def db():
    global _db_conn
    if _db_conn is None:
        print(f"Connecting to database at {DB_PATH}", flush=True)
        _db_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _db_conn.row_factory = sqlite3.Row
    return _db_conn

def init_db():
    print("Initializing database...", flush=True)
    c = db().cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT    UNIQUE NOT NULL,
            created_at TEXT    NOT NULL
        );
    """)
    db().commit()
    print("Database initialized.", flush=True)

async def handle_client(reader, writer):
    addr = writer.get_extra_info("peername")
    print(f"[+] Connection from {addr}", flush=True)
    
    async def send(line):
        try:
            print(f"  Sending to {addr}: {repr(line)}", flush=True)
            writer.write((line + "\n").encode())
            await writer.drain()
            print(f"  Sent.", flush=True)
        except Exception as e:
            print(f"  Send error: {e}", flush=True)
            pass
    
    try:
        print(f"[*] Starting read loop for {addr}", flush=True)
        while True:
            print(f"  Waiting for data from {addr}...", flush=True)
            raw = await reader.readline()
            print(f"  Got {len(raw) if raw else 0} bytes from {addr}: {repr(raw)}", flush=True)
            
            if not raw:
                print(f"  {addr} disconnected", flush=True)
                break
            
            line = raw.decode(errors="replace").strip()
            print(f"  Decoded line: {repr(line)}", flush=True)
            
            if not line:
                print(f"  Empty line, continuing", flush=True)
                continue
            
            parts = line.split(" ", 2)
            cmd = parts[0].upper()
            print(f"  Command: {cmd}", flush=True)
            
            if cmd == "REGISTER":
                print(f"  Handling REGISTER", flush=True)
                if len(parts) < 2:
                    await send("-ERR REGISTER requires a username")
                    continue
                
                uname = parts[1].strip()
                print(f"  Username: {repr(uname)}", flush=True)
                
                if not uname.isalnum():
                    await send("-ERR Username must be alphanumeric")
                    continue
                
                c = db().cursor()
                c.execute(
                    "INSERT OR IGNORE INTO users (username, created_at) VALUES (?, ?)",
                    (uname, datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")),
                )
                db().commit()
                
                await send(f"+OK Registered as {uname}")
                print(f"  REGISTER complete", flush=True)
            elif cmd == "QUIT":
                await send("+OK Goodbye")
                break
            else:
                await send(f"-ERR Unknown command '{cmd}'")
    except Exception as e:
        print(f"[!] Error from {addr}: {e}", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        print(f"[-] {addr} closed", flush=True)

async def main():
    print("main() called", flush=True)
    init_db()
    
    port = DEFAULT_PORT
    server = None
    print(f"Trying to bind to port {port}...", flush=True)
    
    while port < DEFAULT_PORT + MAX_PORT_TRIES:
        try:
            server = await asyncio.start_server(handle_client, HOST, port)
            break
        except OSError as e:
            print(f"  Port {port} in use, trying {port + 1}", flush=True)
            port += 1
    
    if server is None:
        print(f"Could not find an available port", flush=True)
        sys.exit(1)
    
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
    print(f"BF Messaging Server listening on {addrs}", flush=True)
    
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    print("Starting asyncio...", flush=True)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
