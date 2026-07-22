"""
This is a tiny dev server that tells the browser not to cache, so my edits to the
HTML, CSS, and JS show up on a normal refresh. Plain python -m http.server caches
too hard, which is why old versions kept sticking. Run it with python devserve.py
and it serves this folder at http://127.0.0.1:5501.
"""

import http.server
import socketserver

PORT = 5501


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), NoCacheHandler) as httpd:
        print(f"Serving frontend (no-cache) at http://127.0.0.1:{PORT}")
        httpd.serve_forever()
