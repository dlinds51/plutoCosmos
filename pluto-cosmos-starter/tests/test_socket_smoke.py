import pathlib
import socket
import struct
import subprocess
import sys
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parents[1]
CMD = HERE / 'bridge' / 'pluto_bridge.py'
PORT = 17771

def get_frame(sock):
    head = read_n(sock, 4)
    length = struct.unpack('>I', head)[0]
    assert 6 <= length <= 16_384, length
    return head + read_n(sock, length - 4)

def read_n(sock, n):
    pieces = []
    while n > 0:
        b = sock.recv(n)
        if not b:
            raise EOFError
        pieces.append(b)
        n -= len(b)
    return b''.join(pieces)

class SocketSmoke(unittest.TestCase):
    def test_simulated_tcp_session(self):
        with subprocess.Popen([sys.executable, str(CMD), '--simulate', '--port', str(PORT)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as proc:
            conn = None
            try:
                for i in range(40):
                    try:
                        conn = socket.create_connection(('127.0.0.1', PORT), timeout=0.4)
                        break
                    except ConnectionRefusedError:
                        time.sleep(0.05)
                self.assertIsNotNone(conn)
                with conn:
                    conn.settimeout(3)
                    seen_status = False
                    seen_spectrum = False
                    for _ in range(8):
                        p = get_frame(conn)
                        if struct.unpack_from('>H', p, 4)[0] == 1:
                            seen_spectrum = True
                            self.assertEqual(len(p), 4146)
                        elif struct.unpack_from('>H', p, 4)[0] == 2:
                            seen_status = True
                        if seen_status and seen_spectrum:
                            break
                    self.assertTrue(seen_status)
                    self.assertTrue(seen_spectrum)
                    config = struct.pack('>IHQIIIffBB', 36, 100, 1090000000, 1000000,
                                         2000000, 1024, 20.0, 4.0, 0, 5)
                    conn.sendall(config)
                    found = False
                    for _ in range(12):
                        p = get_frame(conn)
                        if struct.unpack_from('>H', p, 4)[0] == 1:
                            center = struct.unpack_from('>f', p, 10)[0]
                            if abs(center - 1090.0) < 0.0001:
                                found = True
                                break
                    self.assertTrue(found)
                    conn.sendall(struct.pack('>IH', 6, 102))
                    p = get_frame(conn)
                    self.assertEqual(struct.unpack_from('>H', p, 4)[0], 2)
                    self.assertIn(b'STOPPED', p)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

if __name__ == '__main__':
    unittest.main()
