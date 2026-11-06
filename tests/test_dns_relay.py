import importlib.util
import ipaddress
import socket
import socketserver
import threading
import unittest
from pathlib import Path
from unittest import mock

spec = importlib.util.spec_from_file_location('dns_relay', Path(__file__).resolve().parents[1] / 'deploy/dns_relay.py')
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)
QUERY = b'\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x03api\x04tmdb\x03org\x00\x00\x01\x00\x01'
REPLY = QUERY[:2] + b'\x81\x80' + QUERY[4:]


class UpstreamUDP(socketserver.BaseRequestHandler):
    def handle(self):
        data, endpoint = self.request
        endpoint.sendto(REPLY, self.client_address)


class UpstreamTCP(socketserver.BaseRequestHandler):
    def handle(self):
        header = relay.exact(self.request, 2)
        relay.exact(self.request, int.from_bytes(header, 'big'))
        self.request.sendall(len(REPLY).to_bytes(2, 'big') + REPLY)


class RelayTests(unittest.TestCase):
    def check_transport(self, tcp):
        server_type = relay.TCPServer if tcp else relay.UDPServer
        upstream_handler = UpstreamTCP if tcp else UpstreamUDP
        handler = relay.TCPHandler if tcp else relay.UDPHandler
        with server_type(('127.0.0.1', 0), upstream_handler) as upstream, server_type(('127.0.0.1', 0), handler) as forward:
            with mock.patch.object(relay, 'UPSTREAM', upstream.server_address), mock.patch.object(relay, 'NETWORK', ipaddress.ip_network('127.0.0.0/8')):
                threads = [threading.Thread(target=s.serve_forever, kwargs={'poll_interval': 0.05}) for s in (upstream, forward)]
                for thread in threads:
                    thread.start()
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as client:
                        client.settimeout(2)
                        client.connect(forward.server_address)
                        client.sendall(len(QUERY).to_bytes(2, 'big') + QUERY if tcp else QUERY)
                        if tcp:
                            length = int.from_bytes(relay.exact(client, 2), 'big')
                            result = relay.exact(client, length)
                        else:
                            result = client.recv(4096)
                        self.assertEqual(result, REPLY)
                finally:
                    forward.shutdown()
                    upstream.shutdown()
                    for thread in threads:
                        thread.join()

    def test_udp_query_and_response(self):
        self.check_transport(False)

    def test_tcp_query_and_response(self):
        self.check_transport(True)
