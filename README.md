# Caddy Full

Caddy Full generates Caddy routes from Docker labels. It supports local services and TLS forwarding to another machine.

TLS passthrough forwards the original encrypted connection without decrypting it. A reads SNI, the domain name in the TLS handshake. If a local label matches, A handles the connection locally. Otherwise, A forwards the connection to B. Each machine obtains and renews certificates for its own services.

## Single machine

Run these commands from the repository root:

```sh
docker compose -f sample/docker-compose.yml up --build -d
```

The demo uses `test1.localhost`, `test2.localhost`, and `test3.localhost`. Its certificates use a local Caddy certificate authority. Browsers require its root certificate to be trusted.

## Two machines

Use the complete [A and B deployment guide](TWO_TIER_SETUP.md). The Compose files are [machine A](sample/two-tier-host1-docker-compose.yml) and [machine B](sample/two-tier-host2-docker-compose.yml).

Both deployment files use `zhuoyin/caddy-full:latest` with `pull_policy: always`. They do not require a local build.

A sets `FALLBACK_PROXY` to B's LAN address and port, such as `192.168.1.20:443`. B leaves `FALLBACK_PROXY` unset. Both machines use TLS validation over TCP 443 by default. Their YAML files do not need `TLS_ALPN_ONLY`. B does not need a public port mapping from the router.

Add labels only to the machine that runs the service:

```yaml
labels:
  caddy.0.domain: app.example.com
  caddy.0.port: "8080"
  caddy.0.tls: admin@example.com
```

The email label is optional. Each service must expose its backend port and share a Docker network with its local proxy. The proxy resolves the Docker container name.

Fallback means an unmatched domain. A local application response of 404 or 502 does not trigger fallback. If A and B declare the same domain, A wins. Do not point B back to A.

If neither machine has a certificate for the requested domain, the TLS handshake fails. The proxy does not request certificates for arbitrary unknown names. Plain HTTP to an unknown name on the final machine returns 404.

## Configuration

- `FALLBACK_PROXY`: next machine as `host:port`, without a URL scheme. An empty value disables forwarding.
- `HTTPS_PORT`: optional override for the local Caddy HTTPS port. Leave it unset for the standard deployment. It defaults to `8443` with fallback and `443` without fallback. Fallback reserves TCP 443.
- `TLS_ALPN_ONLY`: `true` selects ACME validation over TLS on port 443. It defaults to `true`, including when the value is empty. Set it to `false` to also enable HTTP validation on port 80.
- `LOCAL_DOMAINS`: space-separated domains from hand-written `conf.d` sites that A must handle locally. This does not create sites or certificates.
- `CADDY_INSTANCE`: optional label scope when several proxies use one Docker daemon. Matching services require `caddy.instance` with the same value.
- `ACME_CA`: optional ACME directory URL for a staging or test certificate authority.
- `ACME_CA_ROOT`: optional trusted PEM certificate path for a private ACME endpoint.
- `PUID` and `PGID`: optional numeric runtime user and group IDs. The entrypoint grants access to the Docker socket group.
- `UMASK`: optional file creation mask, such as `022`.
- `TZ`: optional timezone, such as `America/New_York`.

ACME is the protocol Caddy uses to obtain certificates. TLS-ALPN-01 validates domain control through a special TLS handshake on port 443.

## Labels

- `caddy.N.domain`: site names separated by spaces or commas. Use bare DNS names for two-machine routing.
- `caddy.N.port`: backend container port, with `80` as the default.
- `caddy.N.paths`: comma-separated `path:port` pairs, such as `api:8081,media:8082`. Paths keep their prefixes.
- `caddy.N.rewrite`: optional Caddy rewrite arguments.
- `caddy.N.tls`: optional Caddy TLS arguments, such as an ACME email or `internal` for local tests.

Replace `N` with `0`, `1`, or another index for each site block. Single-machine configurations also accept explicit site ports. A wildcard site requires a wildcard certificate, normally through DNS validation. Wildcard DNS records alone do not require wildcard certificates.

## Generated files and state

`docker-gen` watches Docker and renders global options and all label routes into one file: `/etc/caddy/default.d/default.caddy`. It reloads Caddy after a change. This keeps the TLS route table and application routes in the same snapshot. Caddy rejects invalid reloads and keeps its active configuration.

The entrypoint manages `/etc/caddy/Caddyfile` and the generated file. Put hand-written site blocks in `/etc/caddy/conf.d/`. Do not add another global options block. After editing a snippet, run:

```sh
docker compose exec rp1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

Replace `rp1` with the proxy service name in your Compose file. On A, also list snippet domains in `LOCAL_DOMAINS`, then recreate the proxy after changing that variable.

Persist both `/etc/caddy` and `/data`. Certificates, account keys, and local certificate authorities live under `/data/caddy`. An `/etc/caddy` mount alone does not preserve certificates. Keep an existing `/data` volume when upgrading.

The Docker socket mount is `/var/run/docker.sock:/tmp/docker.sock:ro`. Docker API access remains privileged even with a read-only socket mount. Only trusted operators can edit routing labels or snippets.

## Network limits

The forwarding path uses TCP. The generated configuration enables HTTP/1.1 and HTTP/2 and disables HTTP/3. Do not publish UDP 443 for this topology. The internal port 8443 requires no host port mapping.

B sees A as the remote peer. Applications behind A's local TCP hop can also see the proxy address. This implementation does not preserve the original client IP through PROXY protocol.

All public DNS A and AAAA records must lead to a working ingress for the domain. B must reach the certificate authority over outbound HTTPS. A must reach B over LAN TCP 443. A CDN that terminates TLS before A prevents this validation path unless it passes the original TLS connection through.

## Build and test

Build the local image from the repository root:

```sh
docker build -t caddy-full:two-tier-test .
./sample/verify-two-tier.sh
```

The test needs Docker, Python 3, OpenSSL, curl with Brotli support, and access to the test container images. It uses Pebble, a local ACME test server, with real TLS-ALPN validation. It creates isolated containers and volumes, then removes them. It does not request public certificates.

See [verification details](VERIFICATION.md). `build.sh` is the existing registry publication script and pushes images. Use `docker build` for local builds.

## References

[Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https) describes certificate validation. [Caddy Layer 4](https://github.com/mholt/caddy-l4) supplies SNI routing and TLS passthrough.
