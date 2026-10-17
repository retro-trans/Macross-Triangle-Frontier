"""Drive PPSSPP through its WebSocket debugger API (standard library only).

PPSSPP must run with the remote debugger on (ppsspp.ini, [General]):
  RemoteDebuggerOnStartup = True
  RemoteDebuggerLocal = True
  RemoteISOPort = 45678          (the port used below)

Usage:
  python tools/ppsspp_ctl.py status
  python tools/ppsspp_ctl.py press <button> [<button> ...] [--frames N] [--wait S]
  python tools/ppsspp_ctl.py shot <out.png>
  python tools/ppsspp_ctl.py send '<json>'
  python tools/ppsspp_ctl.py script <file>   one command per line, e.g.
                                             press cross / wait 2 / shot a.png

Buttons: cross circle triangle square up down left right start select ltrigger rtrigger
"""

import base64
import json
import os
import socket
import struct
import sys
import time

PORT = int(os.environ.get("PPSSPP_PORT", "45678"))


class WS:
    def __init__(self, host="127.0.0.1", port=PORT, path="/debugger"):
        self.s = socket.create_connection((host, port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n"
               "Sec-WebSocket-Protocol: debugger.ppsspp.org\r\n\r\n") % (path, host, port, key)
        self.s.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.s.recv(4096)
            if not chunk:
                raise ConnectionError("no handshake response")
            resp += chunk
        head, self.buf = resp.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise ConnectionError(head.decode(errors="replace"))

    def send(self, obj):
        data = json.dumps(obj).encode()
        hdr = bytearray([0x81])
        n = len(data)
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 65536:
            hdr.append(0x80 | 126)
            hdr += struct.pack(">H", n)
        else:
            hdr.append(0x80 | 127)
            hdr += struct.pack(">Q", n)
        mask = os.urandom(4)
        hdr += mask
        self.s.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.s.recv(1 << 20)
            if not chunk:
                raise ConnectionError("closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        payload = b""
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            data = self._read(n)
            op = b0 & 0x0F
            if op == 9:  # ping
                continue
            payload += data
            if b0 & 0x80:
                return json.loads(payload.decode("utf-8", "replace")) if payload else {}

    def call(self, event, **params):
        """Send a request and return the first reply for the same event (or an error)."""
        ticket = str(time.time())
        msg = dict(params, event=event, ticket=ticket)
        self.send(msg)
        while True:
            r = self.recv()
            if r.get("event") == "error" or r.get("ticket") == ticket:
                return r

    def close(self):
        self.s.close()


def connect(retries=60):
    for _ in range(retries):
        try:
            return WS()
        except OSError:
            time.sleep(1)
    raise SystemExit("PPSSPP debugger not reachable on port %d" % PORT)


def press(ws, buttons, frames=6):
    for b in buttons:
        r = ws.call("input.buttons.press", button=b, duration=frames)
        if r.get("event") == "error":
            raise SystemExit(r)
        time.sleep(frames / 60.0 + 0.15)


def wait_event(ws, name, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        r = ws.recv()
        if r.get("event") in (name, "error"):
            return r
    return None


def window_shot(path):
    """Capture the PPSSPP window client area (Windows only; works when covered)."""
    import ctypes
    from ctypes import wintypes
    from PIL import Image
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.SetProcessDPIAware()
    found = []

    want_pid = int(os.environ.get("PPSSPP_PID", "0"))  # with several PPSSPP windows: only this process's

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if buf.value.startswith("PPSSPP") and user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not want_pid or pid.value == want_pid:
                found.append(hwnd)
        return True

    user32.EnumWindows(enum, 0)
    if not found:
        raise SystemExit("PPSSPP window not found")
    hwnd = found[0]
    rect = wintypes.RECT()
    if user32.IsIconic(hwnd):  # minimized: the client area is empty; restore it without taking focus
        user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
        time.sleep(0.5)
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    w, h = rect.right, rect.bottom
    if not w or not h:
        raise SystemExit("PPSSPP window has no client area (minimized?)")
    hdc = user32.GetDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, 3)  # PW_CLIENTONLY | PW_RENDERFULLCONTENT

    class BMI(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]
    bmi = BMI(ctypes.sizeof(BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1).save(path)
    print("saved", path, "%dx%d" % (w, h))


def shot(ws, path):
    """Grab the display framebuffer as PNG (falls back to a window capture)."""
    ws.send({"event": "cpu.stepping"})
    wait_event(ws, "cpu.stepping")
    try:
        try:
            _shot(ws, path)
            return
        except SystemExit:
            pass
    finally:
        ws.send({"event": "cpu.resume"})
        wait_event(ws, "cpu.resume")
    window_shot(path)


def _shot(ws, path):
    r = ws.call("gpu.buffer.screenshot", type="base64")
    if r.get("event") == "error" or "base64" not in r:
        r = ws.call("gpu.buffer.screenshot", type="uri")
        if "uri" not in r:
            raise SystemExit(r)
        data = base64.b64decode(r["uri"].split(",", 1)[1])
    else:
        data = base64.b64decode(r["base64"])
    open(path, "wb").write(data)
    print("saved", path, "%dx%d" % (r.get("width", 0), r.get("height", 0)))


def run_line(ws, parts):
    cmd = parts[0]
    if cmd == "press":
        frames = 6
        btns = []
        it = iter(parts[1:])
        for p in it:
            if p == "--frames":
                frames = int(next(it))
            else:
                btns.append(p)
        press(ws, btns, frames)
    elif cmd == "wait":
        time.sleep(float(parts[1]))
    elif cmd == "shot":
        shot(ws, parts[1])
    elif cmd == "status":
        print(ws.call("game.status"))
    elif cmd == "send":
        print(json.dumps(ws.call(**json.loads(" ".join(parts[1:]))))[:2000])
    else:
        raise SystemExit("unknown command " + cmd)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    ws = connect()
    try:
        if sys.argv[1] == "script":
            for line in open(sys.argv[2]):
                line = line.split("#", 1)[0].strip()
                if line:
                    run_line(ws, line.split())
        else:
            run_line(ws, sys.argv[1:])
    finally:
        ws.close()


if __name__ == "__main__":
    main()
