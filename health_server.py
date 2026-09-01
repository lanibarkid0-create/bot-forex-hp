"""Simple HTTP health server untuk Render/Koyeb keep-alive.

Jalan di background thread supaya tidak ganggu Telegram polling.
Render free tier: worker tidak butuh healthcheck, tapi kita serve supaya
logging lebih informatif dan bisa dicek uptime-nya.
"""

import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests as _req

START_TIME = time.time()
LAST_HEALTH_CHECK = {"ok": True, "time": time.time()}


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            uptime = int(time.time() - START_TIME)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                f'{{"status":"ok","uptime_sec":{uptime}}}'.encode()
            )
        elif self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"AI BEDAH CHART bot is running.\n")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress access log (terlalu berisik)
        return


def start_health_server():
    """Start HTTP server di background thread."""
    port = int(os.getenv("PORT", "8080"))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(f"[health] server listening on port {port}")
        return server
    except OSError as e:
        # Port mungkin sudah dipakai (kalau di-restart cepat)
        print(f"[health] failed to bind port {port}: {e}")
        return None


if __name__ == "__main__":
    start_health_server()
    # Keep main alive
    while True:
        time.sleep(3600)
