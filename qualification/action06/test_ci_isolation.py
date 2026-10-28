"""Regression tests for the explicit disposable Linux target."""
import os,socket,unittest
from pathlib import Path
import isolation

class IsolationTests(unittest.TestCase):
    def test_external_bind_is_refused_before_socket_can_listen(self):
        with self.assertRaises(PermissionError):
            isolation.audit('socket.bind',(None,('0.0.0.0',55441)))
    def test_external_datagram_is_refused(self):
        with self.assertRaises(PermissionError):
            isolation.audit('socket.sendto',(None,('192.0.2.1',443)))
    def test_wrong_database_target_is_refused(self):
        import psycopg2
        isolation.install()
        with self.assertRaises(PermissionError):
            psycopg2.connect(host='192.0.2.1',port=5432,user='production',dbname='production')
    def test_process_and_secret_access_are_refused(self):
        with self.assertRaises(PermissionError):isolation.audit('subprocess.Popen',())
        with self.assertRaises(PermissionError):isolation.audit('open',('.env','r',0))
    def test_only_reviewed_loopback_endpoints_are_allowed(self):
        isolation.audit('socket.connect',(None,('127.0.0.1',55440)))
        isolation.audit('socket.connect',(None,('127.0.0.1',55441)))
        with self.assertRaises(PermissionError):isolation.audit('socket.connect',(None,('127.0.0.1',5432)))

if __name__=='__main__':unittest.main(verbosity=2)
