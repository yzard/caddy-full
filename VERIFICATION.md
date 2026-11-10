# Verification

The local image build and seven integration tests passed on November 10, 2026. The suite completed in approximately 31 seconds. It covers optional SSH splitting, certificate forwarding, Brotli compression, and runtime configuration.

The SSH update also passed a real OpenSSH handshake against the local host. The shared port reached SSH authentication and presented the same host key as direct port 22. This test did not log in or run a remote command. The `ssh-keyscan` tool timed out because it waits for the server banner before sending identification bytes.

## Commands

Run these commands from the repository root:

```sh
docker build --pull -t caddy-full:ssh-test .
CADDY_TEST_IMAGE=caddy-full:ssh-test ./sample/verify-two-tier.sh
git diff --check
sh -n docker-entrypoint.sh sample/verify-two-tier.sh
docker compose -f sample/docker-compose.yml config -q
FALLBACK_HOST=192.168.1.20 docker compose -f sample/two-tier-host1-docker-compose.yml config -q
docker compose -f sample/two-tier-host2-docker-compose.yml config -q
```

The image reports Caddy `v2.11.9` and docker-gen `0.17.2`. Forego builds from tag `v0.18.8`. All three binaries report Go `1.27.3` in their build metadata. Its module list includes Layer 4 routing and Brotli encoding. The Docker build pins the Caddy plugin revisions and excludes local certificate data from its context.

## Integration coverage

The tests use isolated Docker containers for A, B, applications, and Pebble. Pebble is a local ACME test certificate authority. Its domain validation connects to A on TCP 443. The tests do not bypass ACME validation. HTTPS clients trust the test root and validate the requested domain.

The following behavior passed:

- A and B obtain certificates with SSH splitting enabled and disabled.
- SSH, plain HTTP, and HTTPS share TCP 443 with and without a fallback proxy.
- Fragmented SSH identification bytes and binary payloads reach the SSH backend unchanged.
- SSH stays available after route reloads and while B is down.
- Disabling SSH splitting removes the SSH route and preserves HTTPS with the stored certificate.
- B completes TLS-ALPN-01 validation through A, with no B-only labels on A.
- Both email labels and the default issuer use TLS-ALPN-01 with `TLS_ALPN_ONLY` omitted.
- Multiple names and explicit `:443` labels route correctly through A.
- A takes priority when a local label claims a domain already served by B.
- Removing that local container restores forwarding to B without a proxy restart.
- Unknown domains fail the TLS handshake.
- Local application 404 responses and backend failures stay on A.
- An HTTP Host value that differs from TLS SNI receives 421.
- Port 80 redirects known and unknown domains on A and B to HTTPS on port 443.
- Redirects preserve the path and query and remove incoming Host ports, including 80 and 8080.
- Plain HTTP on the shared port also redirects unknown names to HTTPS.
- B downtime does not interrupt A's local service.
- Recreating B preserves its certificate bytes and restores HTTPS forwarding.
- Existing user IDs, custom group IDs, and Docker socket access work after privilege changes.
- Single-machine internal certificates and hand-written `conf.d` snippets work.
- An empty `TLS_ALPN_ONLY` value uses TLS-only validation, while explicit `false` also enables HTTP validation.
- Invalid ports, conflicting listeners, and invalid runtime values fail at startup.
- Brotli responses decode to their original content with a Brotli-capable curl client.
- The proxy containers stop without a forced kill.

The test containers, networks, and volumes are removed after each test. The local image remains available as `caddy-full:ssh-test`.

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

The fallback route explicitly matches TLS. Both local and fallback routes inspect TLS handshakes before forwarding them.

One generated file contains the global options and HTTP sites. Docker events regenerate that file and invoke `caddy reload`. Both routing tables therefore use the same Docker snapshot.

## Limits

The tests simulate two machines with separate label scopes on one Docker daemon. Real router forwarding, public DNS, ISP restrictions, and firewall rules remain deployment checks. No public certificate was requested, and no production service was deployed.

Certificate persistence and initial issuance were tested. Time-based certificate renewal was not observed. Caddy uses the same configured issuer and inbound validation path for renewal.

HTTP/3 and original client IP propagation are outside this implementation. The generated configuration uses HTTP/1.1 and HTTP/2 over TCP.

## Dependency security update

The image uses Caddy 2.11.9, Go 1.27.3, forego 0.18.8, and docker-gen 0.17.2. The plugins use Layer 4 0.1.2 and Brotli 1.7.0. The Caddy build explicitly selects the configured Go toolchain.

Binary scans with `govulncheck` 1.9.0 found vulnerable dependencies in the initial version-only upgrade. The Dockerfile therefore also pins these dependency patches:

- `golang.org/x/net` 0.62.0 fixes GO-2026-6860 and GO-2026-6866 in Caddy.
- `github.com/klauspost/compress` 1.20.4 includes the fix for GO-2026-6865.
- `golang.org/x/crypto` uses commit `2f1f834330b2`, which removes the obsolete OpenPGP package covered by GO-2026-5932.
- `github.com/fsouza/go-dockerclient` 1.13.3 selects `github.com/moby/go-archive` 0.3.3, which includes the fix for GO-2026-6253.

After rebuilding, `govulncheck -mode=binary` passed for Caddy, forego, and docker-gen. Caddy and docker-gen reported no vulnerabilities. Forego reported no affected symbols or imported packages. It still reported two advisories in required modules outside the code that the scan found in use.

The five integration tests passed on the final image after these dependency changes. The binaries are static and do not require extra runtime shared libraries. This verification covers Go binary advisories and the tested application paths. It does not replace an operating-system package vulnerability scan.

Upstream sources: [Caddy 2.11.9](https://github.com/caddyserver/caddy/releases/tag/v2.11.9), [Go downloads](https://go.dev/dl/), [forego 0.18.8](https://github.com/nginx-proxy/forego/releases/tag/v0.18.8), [docker-gen 0.17.2](https://github.com/nginx-proxy/docker-gen/releases/tag/0.17.2).
