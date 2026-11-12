"""Docker integration tests with real TLS-ALPN validation through A to B.

Run: CADDY_TEST_IMAGE=caddy-full:two-tier-test python3 -m unittest discover -s tests -v
The test creates isolated containers, networks, and volumes, then removes them.
"""

import http.client
import json
import os
from pathlib import Path
import socket
import socketserver
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
import uuid


IMAGE = os.environ.get("CADDY_TEST_IMAGE", "caddy-full:two-tier-test")
PEBBLE = "ghcr.io/letsencrypt/pebble:2.8.0"


def docker(*args):
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=90
    )
    if result.returncode:
        raise AssertionError(f"docker {' '.join(args)}\n{result.stdout}{result.stderr}")
    return result.stdout.strip()


def eventually(action, timeout=50):
    deadline = time.monotonic() + timeout
    while True:
        try:
            return action()
        except (AssertionError, OSError, http.client.HTTPException):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.5)


class TwoTierTest(unittest.TestCase):
    def setUp(self):
        self.prefix = "caddy-test-" + uuid.uuid4().hex[:10]
        self.containers = []
        self.volumes = []
        self.network = self.prefix
        self.temp = tempfile.TemporaryDirectory(prefix=self.prefix)
        self.directory = Path(self.temp.name)
        self.directory.chmod(0o755)
        docker("network", "create", self.network)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for name in reversed(self.containers):
            subprocess.run(["docker", "rm", "-fv", name], capture_output=True)
        for volume in self.volumes:
            subprocess.run(["docker", "volume", "rm", volume], capture_output=True)
        subprocess.run(["docker", "network", "rm", self.network], capture_output=True)
        self.temp.cleanup()

    def start(self, name, args, image=IMAGE, command=()):
        full_name = self.prefix + "-" + name
        if full_name not in self.containers:
            self.containers.append(full_name)
        docker("run", "-d", "--name", full_name, "--network", self.network,
               *args, image, *command)
        return full_name

    def port(self, name, port):
        mapping = docker("port", name, str(port)).splitlines()[0]
        return int(mapping.rsplit(":", 1)[1])

    def request(self, port, domain, path="/", context=None, host=None):
        raw = socket.create_connection(("127.0.0.1", port), timeout=3)
        with raw:
            conn = context.wrap_socket(raw, server_hostname=domain) if context else raw
            with conn:
                conn.sendall(
                    f"GET {path} HTTP/1.1\r\nHost: {host or domain}\r\nConnection: close\r\n\r\n".encode()
                )
                response = http.client.HTTPResponse(conn)
                response.begin()
                return response.status, response.read().decode(), dict(response.getheaders())

    def app(self, name, instance, domain, content, extra=()):
        return self.start(name, [
            "--entrypoint", "sh", "--label", f"caddy.instance={self.prefix}-{instance}",
            "--label", f"caddy.0.domain={domain}", "--label", "caddy.0.port=80", *extra,
        ], image="nginx:1.28-alpine", command=["-c", f"echo {content} > /usr/share/nginx/html/index.html; exec nginx -g 'daemon off;'"])

    def proxy(self, name, fallback=None, acme=False, ssh_proxy=None, extra=()):
        volume = self.prefix + "-" + name + "-data"
        if volume not in self.volumes:
            self.volumes.append(volume)
        args = [
            "-v", "/var/run/docker.sock:/tmp/docker.sock:ro",
            "-v", f"{volume}:/data", "-p", "127.0.0.1::443", "-p", "127.0.0.1::80",
            "-e", f"CADDY_INSTANCE={self.prefix}-{name}",
            "-e", "PUID=1000", "-e", "PGID=1000",
        ]
        if fallback:
            args += ["-e", f"FALLBACK_PROXY={fallback}:443"]
        if ssh_proxy:
            args += ["-e", "SSH_SPLITTER=true", "-e", f"SSH_PROXY={ssh_proxy}",
                     "--add-host", "host.docker.internal:host-gateway"]
        if acme:
            args += ["-v", f"{self.directory}:/test:ro",
                     "-e", "ACME_CA=https://pebble:14000/dir",
                     "-e", "ACME_CA_ROOT=/test/api.pem"]
        if name == "a":
            for domain in ["a.caddy-full.test", "alias.caddy-full.test", "b.caddy-full.test"]:
                args += ["--network-alias", domain]
        return self.start(name, [*args, *extra])

    def ssh_backend(self):
        # A protocol fixture tests byte preservation without a host SSH dependency.
        class SSHBackend(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(5)
                self.request.sendall(b"SSH-2.0-CaddyTest\r\n")
                try:
                    while data := self.request.recv(4096):
                        self.request.sendall(data)
                except (TimeoutError, ConnectionError):
                    pass

        server = socketserver.ThreadingTCPServer(("0.0.0.0", 0), SSHBackend)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"host.docker.internal:{server.server_address[1]}"

    def assert_ssh(self, port):
        with socket.create_connection(("127.0.0.1", port), timeout=3) as conn:
            # Fragment the identifying bytes to exercise protocol detection.
            conn.sendall(b"SS")
            conn.sendall(b"H-2.0-client\r\n")
            stream = conn.makefile("rb")
            with stream:
                self.assertEqual(stream.readline(), b"SSH-2.0-CaddyTest\r\n")
                self.assertEqual(stream.readline(), b"SSH-2.0-client\r\n")
                payload = bytes(range(256)) * 8
                conn.sendall(payload)
                self.assertEqual(stream.read(len(payload)), payload)

    def start_ca(self):
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
            "-subj", "/CN=pebble", "-addext", "subjectAltName=DNS:pebble,DNS:localhost",
            "-keyout", str(self.directory / "api.key"),
            "-out", str(self.directory / "api.pem"),
        ], check=True, capture_output=True)
        (self.directory / "api.key").chmod(0o644)
        (self.directory / "pebble.json").write_text(json.dumps({"pebble": {
            "listenAddress": "0.0.0.0:14000", "managementListenAddress": "0.0.0.0:15000",
            "certificate": "/test/api.pem", "privateKey": "/test/api.key",
            "httpPort": 80, "tlsPort": 443,
        }}))
        ca = self.start("ca", ["--network-alias", "pebble", "-v", f"{self.directory}:/test:ro",
                               "-e", "PEBBLE_VA_NOSLEEP=1", "-e", "PEBBLE_WFE_NONCEREJECT=0",
                               "-e", "PEBBLE_AUTHZREUSE=0", "-p", "127.0.0.1::15000"],
                        image=PEBBLE, command=["-config", "/test/pebble.json"])
        api_context = ssl.create_default_context(cafile=str(self.directory / "api.pem"))
        def root():
            status, pem, _ = self.request(self.port(ca, 15000), "localhost", "/roots/0", api_context)
            self.assertEqual(status, 200)
            return pem
        pem = eventually(root)
        return ca, ssl.create_default_context(cadata=pem)

    def test_certificate_relay_and_dynamic_routes(self):
        self.certificate_relay_and_dynamic_routes(ssh_splitter=False)

    def test_bep_label_on_fallback_proxy(self):
        _, https_context = self.start_ca()
        cert = self.directory / "api.pem"
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(str(cert), str(self.directory / "api.key"))
        server_context.set_alpn_protocols(["bep/1.0"])

        class BEPBackend(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(5)
                with server_context.wrap_socket(self.request, server_side=True) as conn:
                    conn.sendall(conn.recv(1024))

        backend = socketserver.ThreadingTCPServer(("0.0.0.0", 0), BEPBackend)
        backend.daemon_threads = True
        threading.Thread(target=backend.serve_forever, daemon=True).start()
        self.addCleanup(backend.server_close)
        self.addCleanup(backend.shutdown)
        target = f"host.docker.internal:{backend.server_address[1]}"
        b = self.proxy("b", acme=True, extra=[
            "--hostname", "custom-b", "--add-host", "host.docker.internal:host-gateway",
            "--label", f"bep_host_port={target}",
        ])
        a = self.proxy("a", fallback=b, acme=True)
        self.app("web-b", "b", "b.caddy-full.test", "web-b",
                 extra=["--label", "bep_host_port=invalid"])
        port = self.port(a, 443)
        eventually(lambda: self.assertEqual(
            self.request(port, "b.caddy-full.test", context=https_context)[:2],
            (200, "web-b\n"),
        ))
        self.assertNotIn("@bep", docker("exec", a, "cat", "/etc/caddy/default.d/default.caddy"))

        bep_context = ssl.create_default_context(cafile=str(cert))
        bep_context.check_hostname = False
        bep_context.set_alpn_protocols(["bep/1.0"])
        # Native Syncthing connections can arrive without a TLS server name.
        for server_name in (None, "b.caddy-full.test"):
            with socket.create_connection(("127.0.0.1", port), timeout=3) as raw:
                with bep_context.wrap_socket(raw, server_hostname=server_name) as conn:
                    self.assertEqual(conn.selected_alpn_protocol(), "bep/1.0")
                    conn.sendall(b"\x00bep-test\xff")
                    with conn.makefile("rb") as stream:
                        self.assertEqual(stream.read(), b"\x00bep-test\xff")

    def test_ssh_splitter_with_certificate_relay(self):
        self.certificate_relay_and_dynamic_routes(ssh_splitter=True)

    def certificate_relay_and_dynamic_routes(self, ssh_splitter):
        try:
            ca, context = self.start_ca()
            b = self.proxy("b", acme=True)
            ssh_proxy = self.ssh_backend() if ssh_splitter else None
            a = self.proxy("a", fallback=b, acme=True, ssh_proxy=ssh_proxy)
            port = self.port(a, 443)
            # Start with zero labels, then require both HTTP and SNI routes to reload.
            def expect(domain, body, path="/", status=200):
                result = self.request(port, domain, path, context)
                self.assertEqual(result[0], status, result)
                if body is not None:
                    self.assertEqual(result[1].strip(), body, result)
                return result

            eventually(lambda: self.assertEqual(self.request(self.port(a, 80), "ready.test")[0], 301))
            if ssh_splitter:
                eventually(lambda: self.assert_ssh(port))
                status, _, headers = self.request(port, "b.caddy-full.test", "/hello?q=1")
                self.assertEqual(status, 301)
                self.assertEqual(headers["Location"], "https://b.caddy-full.test/hello?q=1")
            eventually(lambda: self.assertEqual(self.request(self.port(b, 80), "ready.test")[0], 301))
            self.app("app-b", "b", "b.caddy-full.test", "machine-b")
            eventually(lambda: expect("b.caddy-full.test", "machine-b"), timeout=100)
            self.app("app-a", "a", "a.caddy-full.test alias.caddy-full.test:443", "machine-a",
                     ["--label", "caddy.0.paths=foo:81", "--label", "caddy.0.tls=admin@example.com"])
            eventually(lambda: expect("a.caddy-full.test", "machine-a"))
            eventually(lambda: expect("alias.caddy-full.test", "machine-a"))
            eventually(lambda: expect("b.caddy-full.test", "machine-b"))
            for proxy in [a, b]:
                self.assertIn('"challenge_type":"tls-alpn-01"', docker("logs", proxy))
                self.assertNotIn('"challenge_type":"http-01"', docker("logs", proxy))
            print("\nPASS: A and B obtained trusted certificates through public A:443", flush=True)
            expect("a.caddy-full.test", None, "/missing", 404)
            expect("a.caddy-full.test", None, "/foo", 502)
            status, _, _ = self.request(port, "a.caddy-full.test", context=context, host="b.caddy-full.test")
            self.assertEqual(status, 421)
            with self.assertRaises(ssl.SSLError):
                self.request(port, "unknown.caddy-full.test", context=context)
            status, _, headers = self.request(self.port(a, 80), "b.caddy-full.test", "/hello?q=1")
            self.assertEqual(status, 301)
            self.assertEqual(headers["Location"], "https://b.caddy-full.test/hello?q=1")
            for proxy in [a, b]:
                for host in ["a.caddy-full.test", "unknown.caddy-full.test", "unknown.caddy-full.test:80", "unknown.caddy-full.test:8080"]:
                    status, _, headers = self.request(self.port(proxy, 80), host, "/hello?q=1")
                    self.assertEqual(status, 301)
                    self.assertEqual(headers["Location"], f"https://{host.split(':')[0]}/hello?q=1")
            print("PASS: unknown TLS fails, application errors stay local, HTTP redirect uses 443", flush=True)

            override = self.app("override", "a", "b.caddy-full.test", "machine-a-override")
            eventually(lambda: expect("b.caddy-full.test", "machine-a-override"))
            docker("rm", "-fv", override)
            eventually(lambda: expect("b.caddy-full.test", "machine-b"))
            print("PASS: local labels take priority and removal restores B fallback", flush=True)
            if ssh_splitter:
                self.assert_ssh(port)

            before = docker("exec", b, "sh", "-c", "find /data/caddy/certificates -name '*.crt' -exec sha256sum {} ';'")
            docker("stop", "-t", "5", b)
            expect("a.caddy-full.test", "machine-a")
            if ssh_splitter:
                self.assert_ssh(port)
            with self.assertRaises(OSError):
                self.request(port, "b.caddy-full.test", context=context)
            docker("rm", "-fv", b)
            b = self.proxy("b", acme=True)
            eventually(lambda: expect("b.caddy-full.test", "machine-b"))
            after = docker("exec", b, "sh", "-c", "find /data/caddy/certificates -name '*.crt' -exec sha256sum {} ';'")
            self.assertEqual(before, after)
            print("PASS: recreating B preserves its certificate and restores forwarding", flush=True)
            docker("stop", "-t", "5", a, b)
            for proxy in [a, b]:
                self.assertNotEqual(docker("inspect", "-f", "{{.State.ExitCode}}", proxy), "137")
        except BaseException:
            for name in self.containers:
                result = subprocess.run(["docker", "logs", "--tail", "70", name], capture_output=True, text=True)
                print(f"\n{name}\n{result.stdout}{result.stderr}", flush=True)
            raise

    def test_ssh_splitter_without_fallback(self):
        _, context = self.start_ca()
        self.app("app-a", "a", "a.caddy-full.test", "standalone")
        proxy = self.proxy("a", acme=True, ssh_proxy=self.ssh_backend())
        port = self.port(proxy, 443)
        eventually(lambda: self.assert_ssh(port))
        eventually(lambda: self.assertEqual(
            self.request(port, "a.caddy-full.test", context=context)[1].strip(), "standalone"
        ), timeout=100)
        status, _, headers = self.request(port, "a.caddy-full.test", "/hello")
        self.assertEqual(status, 301)
        self.assertEqual(headers["Location"], "https://a.caddy-full.test/hello")
        status, _, headers = self.request(port, "unknown.caddy-full.test:443", "/hello?q=1")
        self.assertEqual(status, 301)
        self.assertEqual(headers["Location"], "https://unknown.caddy-full.test/hello?q=1")
        with self.assertRaises(ssl.SSLError):
            self.request(port, "unknown.caddy-full.test", context=context)

        docker("rm", "-fv", proxy)
        proxy = self.proxy("a", acme=True)
        port = self.port(proxy, 443)
        eventually(lambda: self.assertEqual(
            self.request(port, "a.caddy-full.test", context=context)[1].strip(), "standalone"
        ))
        with socket.create_connection(("127.0.0.1", port), timeout=3) as conn:
            conn.sendall(b"SSH-2.0-client\r\n")
            try:
                response = conn.recv(256)
            except ConnectionResetError:
                response = b""
            self.assertFalse(response.startswith(b"SSH-"), response)
        print("PASS: standalone SSH/HTTP/HTTPS and certificates work, disabling removes SSH routing", flush=True)

    def test_internal_tls_with_existing_uid(self):
        self.app("internal-app", "b", "app.localhost", "internal-app",
                 ["--label", "caddy.0.tls=internal"])
        proxy = self.start("b", [
            "-v", "/var/run/docker.sock:/tmp/docker.sock:ro", "-p", "127.0.0.1::443",
            "-e", f"CADDY_INSTANCE={self.prefix}-b", "-e", "PUID=65534", "-e", "PGID=1000",
        ])
        pem = eventually(lambda: docker("exec", proxy, "cat", "/data/caddy/pki/authorities/local/root.crt"))
        context = ssl.create_default_context(cadata=pem)
        port = self.port(proxy, 443)
        eventually(lambda: self.assertEqual(self.request(port, "app.localhost", context=context)[1].strip(), "internal-app"))
        process = docker("exec", proxy, "cat", "/proc/1/status")
        self.assertIn("Uid:\t65534\t65534\t65534\t65534", process)
        self.assertIn("Gid:\t1000\t1000\t1000\t1000", process)
        # Manual snippets still load from the persistent configuration directory.
        snippet = 'manual.localhost {\n tls internal\n respond "manual"\n}\n'
        subprocess.run(["docker", "exec", "-i", proxy, "sh", "-c", "cat > /etc/caddy/conf.d/manual.caddy"],
                       input=snippet, text=True, check=True)
        docker("exec", proxy, "caddy", "reload", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile")
        eventually(lambda: self.assertEqual(self.request(port, "manual.localhost", context=context)[1], "manual"))

    def test_validation_mode_override(self):
        for value, disabled in [("", True), ("false", False)]:
            output = docker(
                "run", "--rm", "-v", "/var/run/docker.sock:/tmp/docker.sock:ro",
                "-e", f"CADDY_INSTANCE={self.prefix}-empty",
                "-e", f"TLS_ALPN_ONLY={value}", IMAGE,
                "cat", "/etc/caddy/default.d/default.caddy",
            )
            self.assertEqual("disable_http_challenge" in output, disabled)

    def test_brotli_response(self):
        payload = "Brotli response from the upgraded Caddy image. " * 100
        (self.directory / "compression.caddy").write_text(
            ':8080 {\n encode br gzip zstd\n respond "' + payload + '"\n}\n'
        )
        proxy = self.start("compression", [
            "--entrypoint", "caddy", "-v", f"{self.directory}:/test:ro",
            "-p", "127.0.0.1::8080",
        ], command=["run", "--config", "/test/compression.caddy", "--adapter", "caddyfile"])
        headers = self.directory / "compression.headers"

        def compressed_response():
            result = subprocess.run([
                "curl", "--fail", "--silent", "--show-error", "--compressed",
                "--noproxy", "*", "-H", "Accept-Encoding: br", "-D", str(headers),
                f"http://127.0.0.1:{self.port(proxy, 8080)}/",
            ], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("content-encoding: br", headers.read_text().lower())
            self.assertEqual(result.stdout, payload)

        eventually(compressed_response)

    def test_invalid_configuration(self):
        for setting in ["HTTPS_PORT=80", "HTTPS_PORT=invalid", "PUID=invalid", "TLS_ALPN_ONLY=invalid", "SSH_SPLITTER=invalid"]:
            result = subprocess.run(["docker", "run", "--rm", "-e", setting, IMAGE], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        result = subprocess.run(["docker", "run", "--rm", "-e", "FALLBACK_PROXY=b:443", "-e", "HTTPS_PORT=443", IMAGE], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reserves port 443", result.stderr)
        for setting in ["HTTPS_PORT=443", "SSH_PROXY=http://host:22", "SSH_PROXY=host:0", "SSH_PROXY=host:65536", "SSH_PROXY=host:22\n}"]:
            result = subprocess.run([
                "docker", "run", "--rm", "-e", "SSH_SPLITTER=true", "-e", setting, IMAGE,
            ], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
