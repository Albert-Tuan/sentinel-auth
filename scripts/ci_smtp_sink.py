#!/usr/bin/env python
"""Sentinel Auth — a minimal SMTP sink that captures the MFA OTP.

The frontend's real-HTTP integration suite has to complete a genuine MFA
handshake: challenge → OTP → verify.  The backend delivers the OTP through
SMTP (``app/auth.py`` → ``_send_otp_email_sync``), so the CI needs a real
SMTP server that captures the message instead of a mock inside the test.

This is a **sink**, not a relay: it accepts the message, appends it to a
log file and never forwards it anywhere.

The log format is the one the integration suite parses::

    TO=['m12admin@example.com'] SUBJECT=Sentinel Auth verification code
    Your Sentinel Auth verification code is 123456. It expires in 5 minutes.

    ---

Usage::

    python scripts/ci_smtp_sink.py --port 1025 --log /tmp/m12_otp_capture.log

It uses only the standard library — no extra dependency has to be installed
for the CI to capture an OTP.
"""
from __future__ import annotations

import argparse
import socketserver
import sys
import threading
from email import message_from_bytes
from typing import List, Optional

#: The banner the sink announces itself with.
BANNER = "220 sentinel-auth-smtp-sink ESMTP ready"

#: The lock that serialises the appends to the log file.
_LOG_LOCK = threading.Lock()


class SmtpHandler(socketserver.StreamRequestHandler):
    """A single SMTP conversation.

    Only the commands ``smtplib`` actually sends for a plain-text message
    are implemented: ``EHLO``/``HELO``, ``MAIL FROM``, ``RCPT TO``,
    ``DATA``, ``RSET``, ``NOOP`` and ``QUIT``.
    """

    #: Set to ``True`` once the client has sent the terminating dot.
    timeout = 30

    def handle(self) -> None:
        recipients: List[str] = []
        sender = ""
        data_lines: List[str] = []
        in_data = False

        self.wfile.write((BANNER + "\r\n").encode("utf-8"))

        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode("utf-8", "replace").rstrip("\r\n")

            if in_data:
                if line == ".":
                    in_data = False
                    self._capture(sender, recipients, data_lines)
                    data_lines = []
                    self._reply("250 Message accepted for delivery")
                else:
                    # A leading dot is doubled by the client; undo it.
                    data_lines.append(line[1:] if line.startswith("..") else line)
                continue

            command = line.split(" ", 1)[0].upper()
            if command in {"EHLO", "HELO"}:
                self.wfile.write(b"250-sentinel-auth-smtp-sink\r\n250 SIZE 1048576\r\n")
            elif command == "MAIL":
                sender = line.partition(":")[2].strip()
                self._reply("250 OK")
            elif command == "RCPT":
                recipients.append(line.partition(":")[2].strip())
                self._reply("250 OK")
            elif command == "DATA":
                in_data = True
                self._reply("354 End data with <CR><LF>.<CR><LF>")
            elif command == "RSET":
                sender = ""
                recipients = []
                data_lines = []
                self._reply("250 OK")
            elif command == "NOOP":
                self._reply("250 OK")
            elif command == "QUIT":
                self._reply("221 Bye")
                return
            else:
                self._reply("250 OK")

    def _reply(self, text: str) -> None:
        self.wfile.write((text + "\r\n").encode("utf-8"))

    def _capture(self, sender: str, recipients: List[str], lines: List[str]) -> None:
        """Append one captured message to the log file."""
        message = message_from_bytes("\n".join(lines).encode("utf-8"))
        subject = message.get("Subject", "")
        body = message.get_payload(decode=True)
        if body is None:
            body = message.get_payload()
        if isinstance(body, bytes):
            body = body.decode("utf-8", "replace")

        block = (
            f"TO={recipients!r} SUBJECT={subject}\n"
            f"{body}\n"
            "---\n"
        )
        with _LOG_LOCK:
            with open(self.server.log_path, "a", encoding="utf-8") as handle:  # type: ignore[attr-defined]
                handle.write(block)
        print(
            f"[smtp-sink] captured a message for {recipients!r}",
            file=sys.stderr,
            flush=True,
        )


class SmtpServer(socketserver.ThreadingTCPServer):
    """A threaded SMTP sink."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, handler, log_path: str):
        super().__init__(address, handler)
        self.log_path = log_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1025)
    parser.add_argument("--log", default="/tmp/m12_otp_capture.log")
    args = parser.parse_args()

    # Truncate the log so a run never reads an OTP from a previous one.
    with open(args.log, "w", encoding="utf-8"):
        pass

    server = SmtpServer((args.host, args.port), SmtpHandler, args.log)
    print(
        f"[smtp-sink] listening on {args.host}:{args.port}, capturing to {args.log}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
