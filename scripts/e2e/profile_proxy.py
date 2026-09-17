"""Forward to the real Profile service; hold responses at a controlled crash point."""

import json
import threading
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Faults:
    hold = threading.Event()
    hold.set()
    mode = "forward"
    completed = 0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def reply(self, status, body=b"", headers=()):
        self.send_response(status)
        for name, value in headers:
            if name.lower() not in {
                "content-length",
                "connection",
                "transfer-encoding",
            }:
                self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError, ConnectionResetError:
            pass

    def do_GET(self):
        self.reply(
            200,
            json.dumps({"mode": Faults.mode, "completed": Faults.completed}).encode(),
        )

    def do_POST(self):
        config = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        Faults.mode = config["mode"]
        Faults.completed = 0
        if Faults.mode == "hold_after_commit":
            Faults.hold.clear()
        else:
            Faults.hold.set()
        self.reply(200, b"{}")

    def do_PUT(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        headers = dict(self.headers)
        mode = Faults.mode
        if mode == "wrong_service_token":
            headers = {
                key: value
                for key, value in headers.items()
                if key.lower() != "x-service-token"
            }
            headers["X-Service-Token"] = "deliberately-invalid-e2e-token"
        connection = HTTPConnection("user-profile-service", 8002, timeout=8)
        try:
            connection.request("PUT", self.path, body=body, headers=headers)
            response = connection.getresponse()
            data = response.read()
            response_headers = response.getheaders()
            if response.status == 204:
                Faults.completed += 1
                if mode == "hold_after_commit":
                    Faults.hold.wait(timeout=90)
            self.reply(response.status, data, response_headers)
        except OSError, TimeoutError:
            self.reply(503, b'{"detail":"Profile transport unavailable"}')
        finally:
            connection.close()


ThreadingHTTPServer(("0.0.0.0", 8010), Handler).serve_forever()
