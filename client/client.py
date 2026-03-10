"""
BF Messaging Client
===================
Each user-initiated action is translated into a protocol command by a
dedicated Brainfuck program:

  Action           BF program          stdin fed to BF       BF stdout (command)
  ───────────────  ──────────────────  ────────────────────  ───────────────────
  Register         register_cmd.bf     <username>\\n          REGISTER alice\\n
  Find user        find_cmd.bf         <username>\\n          FIND bob\\n
  Send message     send_cmd.bf         <to>\\n<text>\\n       SEND bob hello\\n
  Chat history     history_cmd.bf      <username>\\n          HISTORY bob\\n
  Quit             quit_cmd.bf         (none)                 QUIT\\n

The Python runtime:
  1. Prompts the user and collects the raw fields.
  2. Feeds them to the BF program via its stdin.
  3. Reads the formatted command from BF's stdout.
  4. Sends that command over TCP to the server.
  5. Displays the server's response.

A background thread continuously reads the socket so that incoming
"+INCOMING …" push messages are shown in real time even while the menu
is displayed.
"""

from __future__ import annotations

import os
import queue
import socket
import sys
import threading
import time

# ---------------------------------------------------------------------------
# Path setup so we can import the BF interpreter from ../brainfuck/
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from brainfuck.interpreter import run as bf_run  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9999

BF_DIR = os.path.join(_ROOT, "brainfuck")


# ---------------------------------------------------------------------------
# BF runner
# ---------------------------------------------------------------------------

def _load_bf(filename: str) -> str:
    path = os.path.join(BF_DIR, filename)
    with open(path) as fh:
        return fh.read()


def run_bf_command(bf_file: str, stdin_data: str) -> str:
    """Execute a BF command builder and return the protocol command string."""
    source = _load_bf(bf_file)
    return bf_run(source, stdin_data)


# ---------------------------------------------------------------------------
# ChatClient
# ---------------------------------------------------------------------------

class ChatClient:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None
        self.username: str | None = None

        # All non-push server lines go here for the main thread to consume
        self._resp_queue: queue.Queue[str] = queue.Queue()

        # Set when the reader thread exits (connection closed)
        self._disconnected = threading.Event()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.host, self.port))
        self._reader_thread = threading.Thread(
            target=self._socket_reader, daemon=True, name="socket-reader"
        )
        self._reader_thread.start()
        print(f"Connected to {self.host}:{self.port}\n")

    def _socket_reader(self) -> None:
        """Background thread: reads every line from the server socket.

        +INCOMING lines are printed immediately (real-time push).
        All other lines go to the response queue for the main thread.
        """
        try:
            buf = b""
            assert self.sock is not None
            while True:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line_bytes, buf = buf.split(b"\n", 1)
                    line = line_bytes.decode(errors="replace").strip()
                    if not line:
                        continue
                    if line.startswith("+INCOMING "):
                        self._display_incoming(line)
                    else:
                        self._resp_queue.put(line)
        except Exception:
            pass
        finally:
            self._disconnected.set()
            self._resp_queue.put("")  # Unblock any waiting get()

    def _display_incoming(self, line: str) -> None:
        """Pretty-print a real-time push message."""
        # +INCOMING <from> <ts> <message>
        rest = line[len("+INCOMING "):]
        parts = rest.split(" ", 2)
        if len(parts) == 3:
            from_user, ts, msg = parts
            sys.stdout.write(
                f"\n\n  ╔═══ New message ══════════════════════╗\n"
                f"  ║  From : {from_user:<28}║\n"
                f"  ║  Time : {ts:<28}║\n"
                f"  ║  {msg:<37}║\n"
                f"  ╚══════════════════════════════════════╝\n\n"
            )
            sys.stdout.flush()
        else:
            print(line)

    # ------------------------------------------------------------------
    # Low-level send / receive
    # ------------------------------------------------------------------

    def _send_raw(self, command: str) -> None:
        assert self.sock is not None
        self.sock.sendall((command.rstrip("\n") + "\n").encode())

    def _recv_until_terminal(self, multiline: bool = False) -> list[str]:
        """Collect response lines until a terminal line is received.

        Single-response commands (+OK / -ERR / +USER) → multiline=False
        HISTORY (+HIST … +END)                         → multiline=True
        """
        lines: list[str] = []
        while True:
            try:
                line = self._resp_queue.get(timeout=10)
            except queue.Empty:
                lines.append("-ERR Timeout waiting for server response")
                break

            if not line:
                break

            lines.append(line)

            if not multiline:
                # Every non-push line is terminal in single-response mode
                break
            else:
                # Wait for +END or -ERR to close the multi-line exchange
                if line == "+END" or line.startswith("-ERR"):
                    break

        return lines

    # ------------------------------------------------------------------
    # BF-powered commands
    # ------------------------------------------------------------------

    def _show_bf_command(self, cmd: str) -> None:
        """Print the raw BF-generated command for transparency."""
        print(f"  〔BF〕 {cmd.strip()}")

    def do_register(self) -> bool:
        print("─" * 45)
        username = input("  Choose a username: ").strip()
        if not username:
            print("  Username cannot be empty.")
            return False

        cmd = run_bf_command("register_cmd.bf", username + "\n")
        self._show_bf_command(cmd)
        self._send_raw(cmd)

        responses = self._recv_until_terminal()
        for r in responses:
            print(f"  {r}")

        if any(r.startswith("+OK") for r in responses):
            self.username = username
            return True
        return False

    def do_find(self) -> None:
        target = input("  Username to find: ").strip()
        if not target:
            return

        cmd = run_bf_command("find_cmd.bf", target + "\n")
        self._show_bf_command(cmd)
        self._send_raw(cmd)

        for r in self._recv_until_terminal():
            if r.startswith("+USER "):
                _, uname, status = r.split(" ", 2)
                icon = "🟢" if status == "online" else "⚪"
                print(f"  {icon} {uname} is {status}")
            else:
                print(f"  {r}")

    def do_send(self) -> None:
        to_user = input("  To      : ").strip()
        message = input("  Message : ").strip()
        if not to_user or not message:
            print("  Both fields are required.")
            return

        cmd = run_bf_command("send_cmd.bf", to_user + "\n" + message + "\n")
        self._show_bf_command(cmd)
        self._send_raw(cmd)

        for r in self._recv_until_terminal():
            print(f"  {r}")

    def do_history(self) -> None:
        with_user = input("  Chat history with: ").strip()
        if not with_user:
            return

        cmd = run_bf_command("history_cmd.bf", with_user + "\n")
        self._show_bf_command(cmd)
        self._send_raw(cmd)

        responses = self._recv_until_terminal(multiline=True)

        if not responses or (len(responses) == 1 and responses[0].startswith("+END")):
            print(f"  No messages with {with_user} yet.")
            return

        print(f"\n  ── Chat with {with_user} " + "─" * 20)
        for r in responses:
            if r.startswith("+HIST "):
                rest = r[len("+HIST "):]
                parts = rest.split(" ", 2)
                if len(parts) == 3:
                    from_u, ts, msg = parts
                    if from_u == self.username:
                        print(f"  [{ts}]  you → {msg}")
                    else:
                        print(f"  [{ts}]  {from_u} → {msg}")
            elif r == "+END":
                print("  " + "─" * 35)
            else:
                print(f"  {r}")

    def do_quit(self) -> None:
        cmd = run_bf_command("quit_cmd.bf", "")
        self._show_bf_command(cmd)
        self._send_raw(cmd)
        # Give the server a moment to respond
        time.sleep(0.2)

    # ------------------------------------------------------------------
    # Main interactive loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        print()
        print("╔══════════════════════════════════════════╗")
        print("║       BF Messaging — Chat Client         ║")
        print("║  Commands generated by Brainfuck (BF)    ║")
        print("╚══════════════════════════════════════════╝")

        # Registration
        registered = False
        for _ in range(3):
            if self.do_register():
                registered = True
                break
            print("  Try again.")
        if not registered:
            print("Could not register. Exiting.")
            return

        print(f"\n  Logged in as: {self.username}")
        print("  Incoming messages will appear instantly.\n")

        # Main menu
        while not self._disconnected.is_set():
            print(f"\n  [{self.username}] What would you like to do?")
            print("  1  Find a user")
            print("  2  Send a message")
            print("  3  View chat history")
            print("  4  Quit")
            print()

            try:
                choice = input("  > ").strip()
            except (EOFError, KeyboardInterrupt):
                choice = "4"

            if choice == "1":
                self.do_find()
            elif choice == "2":
                self.do_send()
            elif choice == "3":
                self.do_history()
            elif choice == "4":
                self.do_quit()
                break
            else:
                print("  Invalid choice — enter 1, 2, 3, or 4.")

        print("\nDisconnected. Goodbye.")
        if self.sock:
            self.sock.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="BF Messaging Client")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Server host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server port")
    args = parser.parse_args()

    client = ChatClient(host=args.host, port=args.port)
    try:
        client.connect()
        client.run()
    except ConnectionRefusedError:
        print(f"Error: could not connect to {args.host}:{args.port}.")
        print("Make sure the server is running:  python server/server.py")
        sys.exit(1)
