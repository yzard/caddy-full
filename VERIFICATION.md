# Verification

The local image build and four integration tests passed on November 9, 2026. The suite includes an explicit override test and an empty-value default test.

## Commands

Run these commands from the repository root:

```sh
docker build -t caddy-full:two-tier-test .
./sample/verify-two-tier.sh
git diff --check
sh -n docker-entrypoint.sh sample/verify-two-tier.sh
docker compose -f sample/docker-compose.yml config -q
FALLBACK_HOST=192.168.1.20 docker compose -f sample/two-tier-host1-docker-compose.yml config -q
docker compose -f sample/two-tier-host2-docker-compose.yml config -q
```

The image reports Caddy `v2.10.2`. Its module list includes Layer 4 routing and Brotli encoding. The Docker build pins the Caddy plugin revisions and excludes local certificate data from its context.

## Integration coverage

The tests use isolated Docker containers for A, B, applications, and Pebble. Pebble is a local ACME test certificate authority. Its domain validation connects to A on TCP 443. The tests do not bypass ACME validation. HTTPS clients trust the test root and validate the requested domain.

The following behavior passed:

- A and B obtain certificates after their application containers start.
- B completes TLS-ALPN-01 validation through A, with no B-only labels on A.
- Both email labels and the default issuer use TLS-ALPN-01 with `TLS_ALPN_ONLY` omitted.
- Multiple names and explicit `:443` labels route correctly through A.
- A takes priority when a local label claims a domain already served by B.
- Removing that local container restores forwarding to B without a proxy restart.
- Unknown domains fail the TLS handshake.
- Local application 404 responses and backend failures stay on A.
- An HTTP Host value that differs from TLS SNI receives 421.
- HTTP redirects preserve the path and query without exposing port 8443.
- B downtime does not interrupt A's local service.
- Recreating B preserves its certificate bytes and restores HTTPS forwarding.
- Existing user IDs, custom group IDs, and Docker socket access work after privilege changes.
- Single-machine internal certificates and hand-written `conf.d` snippets work.
- An empty `TLS_ALPN_ONLY` value uses TLS-only validation, while explicit `false` also enables HTTP validation.
- Invalid ports, conflicting listeners, and invalid runtime values fail at startup.
- The proxy containers stop without a forced kill.

The test containers, networks, and volumes are removed after each test. The local image remains available as `caddy-full:two-tier-test`.

## Example route output

For A's local names, the generated global options contain this routing block. `machine-b` represents B's reachable LAN address.

```caddyfile
layer4 {
    :443 {
        @known tls sni a.example.com admin.example.com
        route @known {
            proxy 127.0.0.1:8443
        }
        @fallback tls
        route @fallback {
            proxy machine-b:443
        }
    }
}
```

The fallback route explicitly matches TLS. This avoids dropping unmatched handshakes after the local SNI matcher reads the initial bytes with the pinned Layer 4 version.

One generated file contains the global options and HTTP sites. Docker events regenerate that file and invoke `caddy reload`. Both routing tables therefore use the same Docker snapshot.

## Limits

The tests simulate two machines with separate label scopes on one Docker daemon. Real router forwarding, public DNS, ISP restrictions, and firewall rules remain deployment checks. No public certificate was requested, and no production service was deployed.

Certificate persistence and initial issuance were tested. Time-based certificate renewal was not observed. Caddy uses the same configured issuer and inbound validation path for renewal.

HTTP/3 and original client IP propagation are outside this implementation. The generated configuration uses HTTP/1.1 and HTTP/2 over TCP.
