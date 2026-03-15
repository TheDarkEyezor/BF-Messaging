#!/usr/bin/env python3
"""Minimal asyncio server test."""
import asyncio

async def handle_client(reader, writer):
    addr = writer.get_extra_info("peername")
    print(f"[+] New connection from {addr}", flush=True)
    
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            
            msg = line.decode().strip()
            print(f"  Received: {repr(msg)}", flush=True)
            
            response = f"ECHO: {msg}\n"
            writer.write(response.encode())
            await writer.drain()
            print(f"  Sent: {repr(response.strip())}", flush=True)
                
    except Exception as e:
        print(f"[!] Error: {e}", flush=True)
    finally:
        writer.close()
        await writer.wait_closed()
        print(f"[-] Disconnected", flush=True)

async def main():
    server = await asyncio.start_server(handle_client, "0.0.0.0", 9999)
    async with server:
        print("Server listening on :9999", flush=True)
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
