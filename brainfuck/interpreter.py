"""
Brainfuck interpreter.

run(source, stdin_data) -> stdout string

The BF programs in this project act as command builders:
  - stdin_data : raw user input (newline-terminated fields)
  - stdout     : a single protocol command line, e.g. "SEND alice hello\n"
"""

from __future__ import annotations


def run(source: str, stdin_data: str = "") -> str:
    """Execute a Brainfuck program and return its stdout as a string.

    Args:
        source:     BF source code (non-BF characters are treated as comments).
        stdin_data: Data fed to the program's ',' instruction as a string.
                    Reading past the end of the buffer yields 0 (EOF).

    Returns:
        Everything the program wrote with '.'.
    """
    # Strip non-BF characters (everything else is a comment)
    code: list[str] = [c for c in source if c in '><+-.,[]']

    tape: list[int] = [0] * 30_000
    ptr: int = 0
    ip: int = 0

    # Pre-build the jump table so loops run in O(1) per bracket
    jump: dict[int, int] = {}
    stack: list[int] = []
    for i, c in enumerate(code):
        if c == '[':
            stack.append(i)
        elif c == ']':
            if not stack:
                raise ValueError(f"Unmatched ']' at instruction {i}")
            j = stack.pop()
            jump[j] = i
            jump[i] = j
    if stack:
        raise ValueError(f"Unmatched '[' at instruction(s) {stack}")

    input_buf: list[int] = [ord(c) for c in stdin_data]
    output_buf: list[str] = []

    while ip < len(code):
        c = code[ip]

        if c == '>':
            ptr = (ptr + 1) % 30_000
        elif c == '<':
            ptr = (ptr - 1) % 30_000
        elif c == '+':
            tape[ptr] = (tape[ptr] + 1) & 0xFF
        elif c == '-':
            tape[ptr] = (tape[ptr] - 1) & 0xFF
        elif c == '.':
            output_buf.append(chr(tape[ptr]))
        elif c == ',':
            tape[ptr] = input_buf.pop(0) if input_buf else 0
        elif c == '[':
            if tape[ptr] == 0:
                ip = jump[ip]
        elif c == ']':
            if tape[ptr] != 0:
                ip = jump[ip]

        ip += 1

    return ''.join(output_buf)


# ---------------------------------------------------------------------------
# CLI helper – lets you pipe a BF file directly:
#   python interpreter.py send_cmd.bf <<< $'alice\nhello\n'
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python interpreter.py <source.bf> [stdin_data]", file=sys.stderr)
        sys.exit(1)

    bf_path = sys.argv[1]
    with open(bf_path) as fh:
        src = fh.read()

    if len(sys.argv) >= 3:
        stdin_text = sys.argv[2]
    else:
        stdin_text = sys.stdin.read()

    output = run(src, stdin_text)
    sys.stdout.write(output)
