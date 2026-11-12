"""Hermetic local HTTP test server serving deterministic synthetic HTML pages."""

import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar


class SyntheticTestHandler(BaseHTTPRequestHandler):
    """HTTP request handler serving synthetic fixture pages."""

    PAGES: ClassVar[dict[str, str]] = {
        "/": """<!DOCTYPE html>
<html>
<head><title>ATLAS Test Harness</title></head>
<body>
    <h1>Welcome to ATLAS Test Bench</h1>
    <nav>
        <a href="/login" id="nav-login">Login Form</a>
        <a href="/interactive" id="nav-interactive">Interactive Elements</a>
        <a href="/download" id="nav-download">Download File</a>
        <a href="/upload" id="nav-upload">Upload File</a>
    </nav>
    <p id="page-status">Ready</p>
</body>
</html>""",
        "/login": """<!DOCTYPE html>
<html>
<head><title>ATLAS Login</title></head>
<body>
    <h2>User Authentication</h2>
    <form id="login-form" onsubmit="event.preventDefault(); document.getElementById('auth-status').innerText = 'Authenticated';">
        <label for="username">Username</label>
        <input type="text" id="username" name="username" placeholder="Enter username" />
        <br/>
        <label for="password">Password</label>
        <input type="password" id="password" name="password" placeholder="Enter password" />
        <br/>
        <button type="submit" id="submit-btn" role="button">Sign In</button>
    </form>
    <div id="auth-status">Unauthenticated</div>
</body>
</html>""",
        "/interactive": """<!DOCTYPE html>
<html>
<head><title>Interactive Controls</title></head>
<body>
    <h3>Controls Test Page</h3>
    <button id="btn-primary" role="button" onclick="document.getElementById('action-result').innerText = 'Clicked Primary';">Primary Button</button>
    <button id="btn-secondary" role="button" onclick="document.getElementById('action-result').innerText = 'Clicked Secondary';">Secondary Button</button>
    <div id="clickable-box" style="width:100px; height:50px; background:#ccc; cursor:pointer;" onclick="document.getElementById('action-result').innerText = 'Clicked Box';">
        Click Target
    </div>

    <select id="country-select">
        <option value="us">United States</option>
        <option value="ca">Canada</option>
        <option value="uk">United Kingdom</option>
    </select>

    <div id="action-result">None</div>
    <div id="scroll-target" style="margin-top: 1500px;">Deep Footer Element</div>
</body>
</html>""",
        "/upload": """<!DOCTYPE html>
<html>
<head><title>File Upload Page</title></head>
<body>
    <h3>Upload Test</h3>
    <input type="file" id="file-input" onchange="document.getElementById('upload-status').innerText = 'File selected: ' + this.files[0].name;" />
    <div id="upload-status">No file uploaded</div>
</body>
</html>""",
    }

    def do_GET(self) -> None:
        path = self.path.split("?")[0]

        if path == "/download":
            data = b"id,name,value\n1,alpha,100\n2,beta,200\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Disposition", 'attachment; filename="data.csv"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if path in self.PAGES:
            content = self.PAGES[path].encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"Not Found")

    def log_message(self, format: str, *args: object) -> None:
        # Silence standard HTTP access logs during test runs
        pass


class SyntheticServer:
    """Manages background thread running SyntheticTestHandler."""

    def __init__(self) -> None:
        # Find free ephemeral port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()

        self.server = HTTPServer(("127.0.0.1", self.port), SyntheticTestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> str:
        self.thread.start()
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
