from http.client import *
import socket
import errno
import sys

_GLOBAL_DEFAULT_TIMEOUT = object()

def _create_connection(address, timeout=_GLOBAL_DEFAULT_TIMEOUT, source_address=None, *, all_errors=False, proto=0):
    host, port = address
    exceptions = []
    for res in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM):
        af, socktype, _, canonname, sa = res
        sock = None
        try:
            sock = socket.socket(af, socktype, proto)
            # if timeout is not _GLOBAL_DEFAULT_TIMEOUT:
            #     sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sa)
            # Break explicitly a reference cycle
            exceptions.clear()
            return sock

        except Exception as exc:
            if not all_errors:
                exceptions.clear()  # raise only the last error
            exceptions.append(exc)
            if sock is not None:
                sock.close()

    if len(exceptions):
        try:
            if not all_errors:
                raise exceptions[0]
            raise ExceptionGroup("create_connection failed", exceptions)
        finally:
            # Break explicitly a reference cycle
            exceptions.clear()
    else:
        raise "getaddrinfo returns an empty list"

class HTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                 source_address=None, blocksize=8192):
        super().__init__(host, port, timeout, source_address, blocksize)

    def connect(self):
        sys.audit("http.client.connect", self, self.host, self.port)
        self.sock = _create_connection((self.host,self.port), self.timeout, self.source_address, proto=socket.IPPROTO_MPTCP)

        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError as e:
            if e.errno != errno.ENOPROTOOPT:
                raise

        if self._tunnel_host:
            self._tunnel()

def _create_https_context(http_version):
    context = ssl._create_default_https_context()
    # send ALPN extension to indicate HTTP/1.1 protocol
    if http_version == 11:
        context.set_alpn_protocols(['http/1.1'])
    # enable PHA for TLS 1.3 connections if available
    if context.post_handshake_auth is not None:
        context.post_handshake_auth = True
    return context

try:
    import ssl
except ImportError:
    pass
else:
    class HTTPSConnection(HTTPConnection):
        "This class allows communication via SSL."

        default_port = HTTPS_PORT = 443

        def __init__(self, host, port=None,
                     *, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                     source_address=None, context=None, blocksize=8192):
            super(HTTPConnection, self).__init__(host, port, timeout,
                                                  source_address,
                                                  blocksize=blocksize)
            if context is None:
                context = _create_https_context(self._http_vsn)
            self._context = context

        def connect(self):
            super().connect()

            if self._tunnel_host:
                server_hostname = self._tunnel_host
            else:
                server_hostname = self.host

            self.sock = self._context.wrap_socket(self.sock, server_hostname=server_hostname)