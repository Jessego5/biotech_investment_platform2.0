"""
This is a tiny dev server that tells the browser not to cache, so my edits to the
HTML, CSS, and JS show up on a normal refresh. Plain python -m http.server caches
too hard, which is why old versions kept sticking. Run it with python devserve.py
and it serves this folder at http://127.0.0.1:5501.
"""

import http.server
import pathlib
import re
import socketserver

PORT = 5501


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self):
        """
        Serve index.html with a version stamp on each asset it references.

        The no-cache headers above are necessary and are not sufficient. A
        browser that already holds app.js from an earlier visit can keep serving
        it from memory for the life of the tab, so edits appear to have no
        effect, the page renders, nothing errors, and it is simply the old
        code. Stamping each URL with the file's modification time makes it a
        different URL whenever the file changes, which nothing can hold onto.
        """
        if self.path in ("/", "/index.html"):
            page = pathlib.Path(__file__).with_name("index.html")
            html = page.read_text()

            def stamp(match):
                attr, name = match.group(1), match.group(2)
                asset = page.with_name(name)
                if not asset.exists():
                    return match.group(0)
                return f'{attr}="{name}?v={int(asset.stat().st_mtime)}"'

            html = re.sub(r'(src|href)="([\w.-]+\.(?:js|css))"', stamp, html)
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), NoCacheHandler) as httpd:
        print(f"Serving frontend (no-cache) at http://127.0.0.1:{PORT}")
        httpd.serve_forever()
