"""
BF Messaging Client
===================
Each user-initiated action is translated into a protocol command by a
dedicated Brainfuck program:

  Action              BF program              stdin fed to BF         BF stdout (command)
  ──────────────────  ──────────────────────  ──────────────────────  ─────────────────────────────
  Register            register_cmd.bf         <username>\\n            REGISTER alice\\n
  Find user           find_cmd.bf             <username>\\n            FIND bob\\n
  Send message (1:1)  send_cmd.bf             <to>\\n<text>\\n         SEND bob hello\\n
  Chat history (1:1)  history_cmd.bf          <username>\\n            HISTORY bob\\n
  Create group        create_group_cmd.bf     <groupname>\\n           CREATE GROUP dev\\n
  Join group          join_group_cmd.bf       <groupname>\\n           JOIN GROUP dev\\n
  Leave group         leave_group_cmd.bf      <groupname>\\n           LEAVE GROUP dev\\n
  Send to group       send_to_group_cmd.bf    <group>\\n<text>\\n      SEND TO GROUP dev hi\\n
  Group history       group_history_cmd.bf    <groupname>\\n           GROUP HISTORY dev\\n
  Group members       group_members_cmd.bf    <groupname>\\n           GROUP MEMBERS dev\\n
  List groups         list_groups_cmd.bf      (none)                   LIST GROUPS\\n
  List chats          list_chats_cmd.bf       (none)                   LIST CHATS\\n
  Quit                quit_cmd.bf             (none)                   QUIT\\n

The Python runtime:
  1. Prompts the user and collects the raw fields.
  2. Feeds them to the BF program via its stdin.
  3. Reads the formatted command from BF's stdout.
  4. Sends that command over TCP to the server.
  5. Displays the server's response.

A background thread continuously reads the socket so that incoming
"+INCOMING …" and "+INCOMING GROUP …" push messages are shown in real
time even while the hub or a conversation is displayed.

UI: WhatsApp-style hub listing all direct chats and groups; pick by
number/letter to open a conversation.  Missed messages (sent while
offline) are delivered by the server right after login as +INCOMING
push lines, so they appear immediately on connection.
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

_W = 52  # Box / separator width for UI


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

        # Hub state – refreshed from server
        self._chats: list[str] = []   # direct-chat peers
        self._groups: list[str] = []  # group names

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
        """Background thread: reads every line from the server socket."""
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
                    if line.startswith("+INCOMING GROUP "):
                        self._display_group_incoming(line)
                    elif line.startswith("+INCOMING "):
                        self._display_incoming(line)
                    elif line.startswith("+NEW_GROUP "):
                        self._handle_new_group(line)
                    else:
                        self._resp_queue.put(line)
        except Exception:
            pass
        finally:
            self._disconnected.set()
            self._resp_queue.put("")  # Unblock any waiting get()

    def _display_incoming(self, line: str) -> None:
        """Pretty-print a real-time 1:1 push message."""
        # +INCOMING <from> <ts> <message>
        rest = line[len("+INCOMING "):]
        parts = rest.split(" ", 2)
        if len(parts) == 3:
            from_user, ts, msg = parts
            ts_short = ts[11:19] if len(ts) >= 19 else ts
            sys.stdout.write(
                f"\n  ┌── {from_user} → you ({'offline catch-up' if ts < _utcnow()[:10] + 'T' else ts_short}) {'─' * 8}\n"
                f"  │  {msg}\n"
                f"  └{'─' * (_W - 4)}\n\n"
            )
            sys.stdout.flush()
            # Keep chats list up-to-date
            if from_user not in self._chats:
                self._chats.insert(0, from_user)
        else:
            print(line)

    def _display_group_incoming(self, line: str) -> None:
        """Pretty-print a real-time group push message."""
        # +INCOMING GROUP <groupname> <from> <ts> <message>
        rest = line[len("+INCOMING GROUP "):]
        parts = rest.split(" ", 3)
        if len(parts) == 4:
            group, from_user, ts, msg = parts
            ts_short = ts[11:19] if len(ts) >= 19 else ts
            sys.stdout.write(
                f"\n  ┌── [{group}] {from_user} ({'offline catch-up' if ts < _utcnow()[:10] + 'T' else ts_short}) {'─' * 4}\n"
                f"  │  {msg}\n"
                f"  └{'─' * (_W - 4)}\n\n"
            )
            sys.stdout.flush()
        else:
            print(line)

    def _handle_new_group(self, line: str) -> None:
        """Handle a real-time push notification that the user was added to a group."""
        # +NEW_GROUP <groupname>
        groupname = line[len("+NEW_GROUP "):].strip()
        if groupname and groupname not in self._groups:
            self._groups.append(groupname)
        sys.stdout.write(
            f"\n  *** You were added to group '{groupname}' ***\n\n"
        )
        sys.stdout.flush()

    # ------------------------------------------------------------------
    # Low-level send / receive
    # ------------------------------------------------------------------

    def _send_raw(self, command: str) -> None:
        assert self.sock is not None
        try:
            self.sock.sendall((command.rstrip("\n") + "\n").encode())
        except (BrokenPipeError, OSError):
            self._disconnected.set()

    def _recv_until_terminal(self, multiline: bool = False) -> list[str]:
        """Collect response lines until a terminal line is received.

        Single-response commands (+OK / -ERR / +USER)  → multiline=False
        Multi-line  responses  (+HIST … +END, etc.)    → multiline=True
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
                break
            else:
                if line.startswith("+END") or line.startswith("-ERR"):
                    break

        return lines

    # ------------------------------------------------------------------
    # Hub: refresh + draw
    # ------------------------------------------------------------------

    def _show_bf_command(self, cmd: str) -> None:
        print(f"  〔BF〕 {cmd.strip()}")

    def refresh_hub(self) -> None:
        """Query server for the current chats and groups, update local lists."""
        # --- direct chats ---
        cmd = run_bf_command("list_chats_cmd.bf", "")
        self._send_raw(cmd)
        lines = self._recv_until_terminal(multiline=True)
        fetched_chats = [l[len("+CHAT "):] for l in lines if l.startswith("+CHAT ")]
        # Merge: keep any peers already in list (for chats added this session), add new ones
        for peer in fetched_chats:
            if peer not in self._chats:
                self._chats.append(peer)

        # --- groups ---
        cmd = run_bf_command("list_groups_cmd.bf", "")
        self._send_raw(cmd)
        lines = self._recv_until_terminal(multiline=True)
        self._groups = [l[len("+GROUP "):] for l in lines if l.startswith("+GROUP ")]

    def draw_hub(self) -> None:
        """Print the WhatsApp-style main screen."""
        print()
        print("╔" + "═" * (_W - 2) + "╗")
        _hub_row(f"  BF Messaging  ·  {self.username}")
        print("╠" + "═" * (_W - 2) + "╣")
        _hub_row("  DIRECT CHATS")
        if self._chats:
            for i, peer in enumerate(self._chats, 1):
                _hub_row(f"   {i})  {peer}")
        else:
            _hub_row("   (none yet — send someone a message first)")
        print("╠" + "═" * (_W - 2) + "╣")
        _hub_row("  GROUPS")
        if self._groups:
            for i, grp in enumerate(self._groups):
                letter = chr(ord("A") + i)
                _hub_row(f"   {letter})  {grp}")
        else:
            _hub_row("   (none yet — create or join a group)")
        print("╠" + "═" * (_W - 2) + "╣")
        _hub_row("  [n] New chat       [c] Create group")
        _hub_row("  [j] Join group     [l] Leave group")
        _hub_row("  [r] Refresh        [q] Quit")
        print("╚" + "═" * (_W - 2) + "╝")

    # ------------------------------------------------------------------
    # Conversation screens
    # ------------------------------------------------------------------

    def open_chat(self, peer: str) -> None:
        """Enter a 1:1 conversation screen."""
        cmd = run_bf_command("history_cmd.bf", peer + "\n")
        self._send_raw(cmd)
        lines = self._recv_until_terminal(multiline=True)

        print()
        print("─" * _W)
        print(f"  {self.username} ↔ {peer}")
        print("─" * _W)
        for l in lines:
            if l.startswith("+HIST "):
                rest = l[6:]
                parts = rest.split(" ", 2)
                if len(parts) == 3:
                    from_u, ts, msg = parts
                    ts_s = ts[11:19] if len(ts) >= 19 else ts
                    label = "you" if from_u == self.username else from_u
                    print(f"  [{ts_s}] {label}: {msg}")
        print("─" * _W)
        print("  Type a message  (blank line = back):")
        print()

        while not self._disconnected.is_set():
            try:
                text = input("  > ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not text:
                break
            cmd = run_bf_command("send_cmd.bf", peer + "\n" + text + "\n")
            self._show_bf_command(cmd)
            self._send_raw(cmd)
            for r in self._recv_until_terminal():
                if not r.startswith("+OK"):
                    print(f"  {r}")

        # Ensure peer appears in the hub chats list
        if peer not in self._chats:
            self._chats.insert(0, peer)

    def open_group(self, group: str) -> None:
        """Enter a group conversation screen."""
        cmd = run_bf_command("group_history_cmd.bf", group + "\n")
        self._send_raw(cmd)
        lines = self._recv_until_terminal(multiline=True)

        print()
        print("─" * _W)
        print(f"  Group: {group}")
        print("─" * _W)
        for l in lines:
            if l.startswith("+GHIST "):
                rest = l[7:]
                parts = rest.split(" ", 2)
                if len(parts) == 3:
                    from_u, ts, msg = parts
                    ts_s = ts[11:19] if len(ts) >= 19 else ts
                    label = "you" if from_u == self.username else from_u
                    print(f"  [{ts_s}] {label}: {msg}")
        print("─" * _W)
        print("  Type a message  (/members = list members   /add <user> = add member   blank line = back):")
        print()

        while not self._disconnected.is_set():
            try:
                text = input("  > ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not text:
                break
            if text.lower() == "/members":
                cmd = run_bf_command("group_members_cmd.bf", group + "\n")
                self._send_raw(cmd)
                for r in self._recv_until_terminal():
                    if r.startswith("+MEMBERS "):
                        member_part = r[len(f"+MEMBERS {group} "):]
                        print(f"  Members of {group}: {member_part}")
                    else:
                        print(f"  {r}")
                continue
            if text.lower().startswith("/add "):
                target = text[5:].strip()
                if not target:
                    print("  Usage: /add <username>")
                    continue
                cmd = run_bf_command("add_member_cmd.bf", group + "\n" + target + "\n")
                self._show_bf_command(cmd)
                self._send_raw(cmd)
                for r in self._recv_until_terminal():
                    print(f"  {r}")
                continue
            cmd = run_bf_command("send_to_group_cmd.bf", group + "\n" + text + "\n")
            self._show_bf_command(cmd)
            self._send_raw(cmd)
            for r in self._recv_until_terminal():
                if not r.startswith("+OK"):
                    print(f"  {r}")

    # ------------------------------------------------------------------
    # Hub actions
    # ------------------------------------------------------------------

    def do_new_chat(self) -> None:
        print("─" * _W)
        peer = input("  Username to chat with: ").strip()
        if not peer:
            return
        cmd = run_bf_command("find_cmd.bf", peer + "\n")
        self._show_bf_command(cmd)
        self._send_raw(cmd)
        resp = self._recv_until_terminal()
        for r in resp:
            if r.startswith("+USER "):
                parts = r.split(" ", 2)
                icon = "online" if len(parts) > 2 and parts[2] == "online" else "offline"
                print(f"  {peer} is {icon}")
                self.open_chat(peer)
                return
            else:
                print(f"  {r}")

    def do_create_group(self) -> None:
        print("─" * _W)
        name = input("  New group name: ").strip()
        if not name:
            return
        cmd = run_bf_command("create_group_cmd.bf", name + "\n")
        self._show_bf_command(cmd)
        self._send_raw(cmd)
        for r in self._recv_until_terminal():
            print(f"  {r}")
            if r.startswith("+GROUP") and name not in self._groups:
                self._groups.append(name)

    def do_join_group(self) -> None:
        print("─" * _W)
        name = input("  Group name to join: ").strip()
        if not name:
            return
        cmd = run_bf_command("join_group_cmd.bf", name + "\n")
        self._show_bf_command(cmd)
        self._send_raw(cmd)
        for r in self._recv_until_terminal():
            print(f"  {r}")
            if r.startswith("+OK Joined") and name not in self._groups:
                self._groups.append(name)

    def do_leave_group(self) -> None:
        print("─" * _W)
        if not self._groups:
            print("  You are not a member of any groups.")
            return
        print("  Your groups:")
        for i, g in enumerate(self._groups):
            print(f"    {i + 1})  {g}")
        choice = input("  Number to leave (or name): ").strip()
        if not choice:
            return
        if choice.isdigit() and 1 <= int(choice) <= len(self._groups):
            name = self._groups[int(choice) - 1]
        else:
            name = choice
        cmd = run_bf_command("leave_group_cmd.bf", name + "\n")
        self._show_bf_command(cmd)
        self._send_raw(cmd)
        for r in self._recv_until_terminal():
            print(f"  {r}")
            if r.startswith("+OK Left") and name in self._groups:
                self._groups.remove(name)

    def do_register(self) -> bool:
        print("─" * _W)
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

    def do_quit(self) -> None:
        cmd = run_bf_command("quit_cmd.bf", "")
        self._show_bf_command(cmd)
        self._send_raw(cmd)
        time.sleep(0.2)

    # ------------------------------------------------------------------
    # Main interactive loop (WhatsApp-style hub)
    # ------------------------------------------------------------------

    def run(self) -> None:
        print()
        print("╔" + "═" * (_W - 2) + "╗")
        _hub_row("  BF Messaging Client")
        _hub_row("  Commands generated by Brainfuck (BF)")
        print("╚" + "═" * (_W - 2) + "╝")

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
        print("  Fetching your chats and groups …")
        # Brief pause so any missed-message push lines arrive before we query
        time.sleep(0.3)
        self.refresh_hub()

        # Hub loop
        while not self._disconnected.is_set():
            self.draw_hub()
            try:
                choice = input("\n  > ").strip()
            except (EOFError, KeyboardInterrupt):
                choice = "q"

            if not choice:
                continue

            # Named commands take priority over letter shortcuts
            if choice == "n":
                self.do_new_chat()
            elif choice == "c":
                self.do_create_group()
            elif choice == "j":
                self.do_join_group()
            elif choice == "l":
                self.do_leave_group()
            elif choice == "r":
                print("  Refreshing …")
                self.refresh_hub()
            elif choice == "q":
                self.do_quit()
                break

            # Numeric → open direct chat by number
            elif choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(self._chats):
                    self.open_chat(self._chats[idx])
                else:
                    print(f"  No chat #{choice}.")

            # Single uppercase/lowercase letter → open group by letter (A, B, C …)
            elif len(choice) == 1 and choice.isalpha():
                idx = ord(choice.upper()) - ord("A")
                if 0 <= idx < len(self._groups):
                    self.open_group(self._groups[idx])
                else:
                    print(f"  No group '{choice.upper()}'.")

            else:
                print("  Unknown command.")

        print("\nDisconnected. Goodbye.")
        if self.sock:
            self.sock.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hub_row(text: str) -> None:
    """Print a fixed-width box row."""
    inner = _W - 4  # 2 border chars + 2 padding spaces
    print(f"║ {text:<{inner}} ║")


def _utcnow() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


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

