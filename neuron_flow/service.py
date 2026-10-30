"""Loopback-only authenticated HTTP admission; one separate supervised worker."""

import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import re
import threading
from urllib.parse import parse_qs, urlsplit

from .operations import JobQueue
from .supervision import load_json, wire

MAX_HTTP_BYTES = 24 * 1024 * 1024


class LocalServer(HTTPServer):
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address


def create_server(queue, read_token, write_token, port=8765):
    if (not isinstance(read_token, str) or not isinstance(write_token, str)
            or len(read_token) < 32 or len(write_token) < 32 or read_token == write_token
            or not read_token.isascii() or not write_token.isascii()):
        raise ValueError('Use distinct ASCII read/write tokens of at least 32 characters')
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('Invalid port')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, value):
            data = wire(value)
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(data)
            self.close_connection = True

        def dispatch(self, writing):
            supplied = self.headers.get('Authorization', '').removeprefix('Bearer ')
            if not supplied.isascii():
                supplied = ''
            if not hmac.compare_digest(supplied, write_token) and (writing or not hmac.compare_digest(supplied, read_token)):
                return self.respond(403, {'error': 'FORBIDDEN'})
            parsed = urlsplit(self.path)
            path = parsed.path
            body = None
            if writing:
                if self.headers.get('Transfer-Encoding') or not self.headers.get('Content-Length', '').isdigit():
                    return self.respond(411, {'error': 'Content-Length required; chunked requests unsupported'})
                size = int(self.headers['Content-Length'])
                if size > MAX_HTTP_BYTES:
                    return self.respond(413, {'error': 'Request body exceeds 24 MiB'})
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    return self.respond(415, {'error': 'application/json required'})
                body = load_json(self.rfile.read(size))
            try:
                if not writing and path == '/health':
                    return self.respond(200, {'status': 'READY', 'scope': 'Single-machine loopback service'})
                if not writing and path == '/metrics':
                    return self.respond(200, queue.metrics())
                if writing and path == '/jobs':
                    return self.respond(202, queue.submit(body))
                match = re.fullmatch(r'/jobs/([a-f0-9]{32})(/events|/cancel)?', path)
                if match:
                    identifier, action = match.groups()
                    if not writing and action is None:
                        return self.respond(200, queue.status(identifier))
                    if not writing and action == '/events':
                        query = parse_qs(parsed.query)
                        return self.respond(200, {'events': queue.events(identifier, int(query.get('after', ['0'])[0]))})
                    if writing and action == '/cancel':
                        if body != {}:
                            raise ValueError('Cancel request must be an empty JSON object')
                        return self.respond(200, queue.cancel(identifier))
                return self.respond(404, {'error': 'Unknown route'})
            except KeyError:
                return self.respond(404, {'error': 'Unknown job'})
            except (ValueError, TypeError, RuntimeError) as exc:
                text = str(exc)
                status = 429 if text.startswith('QUEUE_FULL') else 409 if text.startswith('IDEMPOTENCY_CONFLICT') or isinstance(exc, RuntimeError) else 400
                return self.respond(status, {'error': text[:1000]})

        def handle_request(self, writing):
            try:
                self.dispatch(writing)
            except (ValueError, TypeError, TimeoutError, OSError) as exc:
                try:
                    self.respond(400, {'error': type(exc).__name__})
                except OSError:
                    pass

        def do_GET(self):
            self.handle_request(False)

        def do_POST(self):
            self.handle_request(True)

    return LocalServer(('127.0.0.1', port), Handler)


def serve(workspace, read_token, write_token, port=8765):
    queue = JobQueue(workspace)
    stop = threading.Event()
    server = None
    thread = None
    try:
        server = create_server(queue, read_token, write_token, port)
        def worker():
            while not stop.is_set():
                try:
                    if queue.drain_one() is None:
                        stop.wait(.1)
                except (ValueError, RuntimeError):
                    stop.wait(.1)
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        try:
            server.serve_forever(poll_interval=.1)
        except KeyboardInterrupt:
            pass
    finally:
        stop.set()
        queue.stop_requested.set()
        if thread is not None:
            thread.join(10)
        if server is not None:
            server.server_close()
        queue.close()
    return {'status': 'STOPPED'}
