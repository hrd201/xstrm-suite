"""Expose the host's existing DNS forwarder only to the isolated test bridge."""
import ipaddress
import socket
import socketserver
import threading

LISTEN = ('172.18.0.1', 53)
UPSTREAM = ('127.0.0.1', 1053)
NETWORK = ipaddress.ip_network('172.18.0.0/16')


def allowed(address):
    return ipaddress.ip_address(address) in NETWORK


def exact(stream, size):
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.recv(size - len(chunks))
        if not chunk:
            raise ConnectionError('incomplete DNS message')
        chunks.extend(chunk)
    return bytes(chunks)


class UDPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        if not allowed(self.client_address[0]):
            return
        data, server = self.request
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as upstream:
                upstream.settimeout(5)
                upstream.connect(UPSTREAM)
                upstream.send(data)
                reply = upstream.recv(65535)
            if reply[:2] == data[:2]:
                server.sendto(reply, self.client_address)
        except OSError:
            pass


class TCPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        if not allowed(self.client_address[0]):
            return
        try:
            self.request.settimeout(5)
            header = exact(self.request, 2)
            data = exact(self.request, int.from_bytes(header, 'big'))
            with socket.create_connection(UPSTREAM, timeout=5) as upstream:
                upstream.sendall(header + data)
                response_header = exact(upstream, 2)
                response = exact(upstream, int.from_bytes(response_header, 'big'))
            if response[:2] == data[:2]:
                self.request.sendall(response_header + response)
        except (OSError, ConnectionError):
            pass


class UDPServer(socketserver.ThreadingUDPServer):
    allow_reuse_address = True
    daemon_threads = True


class TCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == '__main__':
    with UDPServer(LISTEN, UDPHandler) as udp, TCPServer(LISTEN, TCPHandler) as tcp:
        threading.Thread(target=tcp.serve_forever, daemon=True).start()
        udp.serve_forever()
