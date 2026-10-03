"""Shows decrypted answer crops during `hs review` without writing them to disk.

A small web server on 127.0.0.1 serves the current crop from memory, at a random
secret path, with no-store headers so the browser doesn't cache it. One browser tab
follows along as you move through the review queue.
"""

import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = """<!doctype html><meta charset="utf-8"><title>hs review</title>
<body style="font:16px system-ui;margin:2em;background:#fafafa">
<p id="c"></p><img id="i" style="width:640px;max-width:100%;border:1px solid #ccc;background:#fff">
<script>
let v = -1;
async function tick() {
  try {
    const r = await fetch("v", {cache: "no-store"});
    const [n, caption] = (await r.text()).split("\\n");
    if (+n !== v) { v = +n; document.getElementById("i").src = "crop.png?" + v;
                    document.getElementById("c").textContent = caption; }
  } catch (e) { document.getElementById("c").textContent = "Review finished. You can close this tab."; return; }
  setTimeout(tick, 500);
}
tick();
</script>"""


class Viewer:
    def __init__(self, open_browser=True):
        self.token = secrets.token_urlsafe(16)
        self.png, self.caption, self.version = b"", "", 0
        self.open_browser, self.opened = open_browser, False
        viewer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path.split("?")[0]
                prefix = f"/{viewer.token}/"
                routes = {prefix: ("text/html; charset=utf-8", PAGE.encode()),
                          prefix + "v": ("text/plain; charset=utf-8", f"{viewer.version}\n{viewer.caption}".encode()),
                          prefix + "crop.png": ("image/png", viewer.png)}
                if path not in routes:
                    self.send_error(404)
                    return
                ctype, body = routes[path]
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/{self.token}/"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def show(self, png: bytes, caption: str):
        self.png, self.caption = png, caption
        self.version += 1
        if self.open_browser and not self.opened:
            self.opened = True
            webbrowser.open(self.url)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.png = b""
