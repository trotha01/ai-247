"""Serve site/ at / and a stream directory at /stream/. Usage: serve.py STREAMDIR [PORT].
Control endpoints for tests: /__mode/ok, /__mode/404 (playlist returns 404), /__mode/freeze (playlist ok, segments hang)."""
import http.server, os, sys, functools, threading, time

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAM = os.path.abspath(sys.argv[1])
MODE = {"m": "ok"}

class H(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        p = path.split("?")[0]
        if p.startswith("/stream/"):
            return os.path.join(STREAM, p[len("/stream/"):])
        return super().translate_path(path)
    def do_GET(self):
        p = self.path.split("?")[0]
        if p.startswith("/__mode/"):
            MODE["m"] = p.split("/")[-1]
            self.send_response(200); self.end_headers(); self.wfile.write(MODE["m"].encode()); return
        if p.startswith("/stream/"):
            if MODE["m"] == "404" and p.endswith(".m3u8"):
                self.send_error(404); return
            if MODE["m"] == "freeze" and p.endswith(".ts"):
                time.sleep(120); return
        return super().do_GET()
    def end_headers(self):
        self.send_header("Cache-Control", "no-store"); super().end_headers()
    def log_message(self, *a): pass

if __name__ == "__main__":
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(H, directory=SITE))
    srv.serve_forever()
