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

A receives public HTTPS traffic. It handles its local domains and forwards other TLS connections to B. B handles its local domains without forwarding back to A.

Both machines use `ghcr.io/yzard/caddy-full:latest` from GitHub Container Registry (GHCR). Neither machine needs the source repository or a local build. The following examples include the proxy and a sample Nginx application on each machine.

```text
https://a.example.com -> A:443 -> rp1's internal HTTPS listener -> app-a:80
https://b.example.com -> A:443 -> B:443 -> rp2 -> app-b:80
```

### Prepare the network

1. Point `a.example.com` and `b.example.com` to the public IP of A's router.
2. Forward public TCP 443 to A's TCP 443.
3. For HTTP redirects, also forward public TCP 80 to A.
4. Give B a stable LAN address, such as `192.168.1.20`.
5. Allow A to connect to B on TCP 443.
6. Allow both machines to resolve DNS names and make outbound HTTPS connections.

Certificate validation uses TCP 443 by default. It does not require public TCP 80 or a router forwarding rule directly to B. Any public AAAA record must also lead to a working IPv6 entry point on A.

### Machine A

Save this file as `compose.yaml` in a deployment directory on A. Replace `192.168.1.20` with B's LAN IP. Replace the domain and email with your values.

```yaml
services:
  rp1:
    image: ghcr.io/yzard/caddy-full:latest
    pull_policy: always
    restart: unless-stopped
    environment:
      FALLBACK_PROXY: "192.168.1.20:443"
      SSH_SPLITTER: "true"
      PUID: "1000"
      PGID: "1000"
      UMASK: "022"
      TZ: America/New_York
    extra_hosts:
      - "host.docker.internal:host-gateway"
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/tmp/docker.sock:ro
      - ./caddy-config:/etc/caddy
      - ./caddy-data:/data
    networks:
      - proxy

  app-a:
    image: nginx:alpine
    restart: unless-stopped
    labels:
      caddy.0.domain: a.example.com
      caddy.0.port: "80"
      caddy.0.tls: admin@example.com
    networks:
      - proxy

networks:
  proxy:
    driver: bridge
```

`FALLBACK_PROXY` selects B as the destination for domains that A does not handle. A automatically uses internal port 8443 for its local HTTPS listener. You do not need `HTTPS_PORT` in the YAML or a host mapping for port 8443.

### Machine B

Save this file as `compose.yaml` in a deployment directory on B. Replace the domain and email with your values. Leave `FALLBACK_PROXY` unset on B.

```yaml
services:
  rp2:
    image: ghcr.io/yzard/caddy-full:latest
    pull_policy: always
    restart: unless-stopped
    environment:
      PUID: "1000"
      PGID: "1000"
      UMASK: "022"
      TZ: America/New_York
    ports:
      - "443:443"
    volumes:
      - /var/run/docker.sock:/tmp/docker.sock:ro
      - ./caddy-config:/etc/caddy
      - ./caddy-data:/data
    networks:
      - proxy

  app-b:
    image: nginx:alpine
    restart: unless-stopped
    labels:
      caddy.0.domain: b.example.com
      caddy.0.port: "80"
      caddy.0.tls: admin@example.com
    networks:
      - proxy

networks:
  proxy:
    driver: bridge
```

The `proxy` network exists separately on each machine. Each application shares a Docker network with its local proxy. A reaches B through its LAN IP, without a shared Docker network or Docker socket.

### Start and update

On each machine, run this command beside its `compose.yaml`:

```sh
docker compose up -d
```

After each push to `main`, a successful GitHub Actions build and test run publishes the new GHCR `latest` image. Running containers do not update automatically.

`pull_policy: always` makes Compose pull the current proxy image when this command runs. After publication, run the same command on A and B to apply the newer image. Certificate and configuration directories remain mounted across container recreation.

On A, read the proxy logs:

```sh
docker compose logs -f rp1
```

On B, read the proxy and certificate logs:

```sh
docker compose logs -f rp2
```

### Certificate issuance

ACME is the protocol Caddy uses to obtain certificates. A certificate authority, such as Let's Encrypt, verifies domain control before issuing a certificate. TLS-ALPN-01 performs that verification through a special TLS handshake on TCP 443.

For `b.example.com`, the process is:

1. B's docker-gen reads the `app-b` labels and generates a Caddy site for `b.example.com`.
2. B's rp2 contacts the certificate authority over outbound HTTPS and requests a certificate for that name.
3. The authority resolves `b.example.com` through public DNS and connects to port 443, which reaches A.
4. A's rp1 reads the domain from the TLS handshake and finds no matching local site.
5. rp1 forwards the original encrypted validation connection to B's rp2, which answers the challenge.
6. After successful validation, rp2 downloads and stores the certificate and its private key under `/data/caddy`.

rp2 does not need to know about rp1. Public DNS and A's `FALLBACK_PROXY` route the authority's validation connection to B. The outbound certificate request uses B's normal network route. It only travels through A if A is separately configured as B's network gateway.

For `a.example.com`, rp1 requests its own certificate. A forwards its validation connection to its own internal HTTPS listener instead of B. Each proxy stores and automatically renews its own certificates. Renewal requires the same network path to remain available.

`TLS_ALPN_ONLY` defaults to `true` on both machines, so the YAML examples omit it. This disables HTTP validation on port 80 and selects TLS validation on port 443. It controls certificate validation, not whether the proxy acts as a gateway.

The `caddy.0.tls` email label is optional. B's service labels stay on B, and its certificate and private key stay on B. Neither labels nor certificates need to be copied to A.

The `./caddy-data:/data` mount preserves certificates and ACME account keys. The separate `./caddy-config:/etc/caddy` mount preserves custom site snippets. Keep both directories when updating the containers.

### Request routing

For a normal request to `https://b.example.com`, rp1 forwards the TLS connection to rp2. rp2 presents its certificate, decrypts the request, and proxies it over HTTP to `app-b:80`. The response returns through rp2 and rp1 to the client. rp1 does not decrypt B's HTTPS traffic.

Fallback means an unmatched domain. A local application response of 404 or 502 does not trigger fallback. If both machines declare the same domain, A wins and B cannot complete new validation for that domain through A. Do not point B back to A.

If neither machine has a certificate for a requested domain, the TLS handshake fails. The proxies do not request certificates for arbitrary unknown names. If B is unavailable, A's local services remain available.

To add a service, create its DNS record and labels only on the machine that runs it. Set `caddy.N.port` to the application's internal listening port. If the image does not expose that port, add Compose `expose`. Docker events update the routes automatically.

See the [deployment guide](TWO_TIER_SETUP.md) for migration notes and custom snippets. Download the sample files for [machine A](sample/two-tier-host1-docker-compose.yml) and [machine B](sample/two-tier-host2-docker-compose.yml).

## SSH on the HTTPS port

The A example enables `SSH_SPLITTER=true`. Caddy Layer 4 identifies SSH, HTTP, and TLS from the first bytes of each connection on TCP 443. It forwards SSH to the host's SSH server and keeps the existing HTTPS routes. This feature uses the existing Caddy process without Nginx.

`SSH_SPLITTER` defaults to `false` when omitted or empty. Set it to `true` to enable splitting, including on a single machine without `FALLBACK_PROXY`. `SSH_PROXY` defaults to `host.docker.internal:22`. Set `SSH_PROXY` to another `host:port` if the host uses a different SSH port.

The Compose `extra_hosts` entry maps `host.docker.internal` to the Docker host gateway. Container loopback addresses refer to the container, not the host. The host SSH server must listen on an address reachable from Docker. Allow that connection through the host firewall.

With A's example running, connect to A through port 443:

```sh
ssh -p 443 your-user@a.example.com
```

SSH uses the host's existing accounts, host keys, and authentication. It does not use HTTPS certificates or wrap SSH in TLS. SSH sends no TLS SNI domain, so all SSH connections to A's port 443 reach A's configured SSH destination. They do not follow the domain fallback to B.

The SSH client must send its identification bytes first. The standard OpenSSH `ssh` client works. Tools that wait for the server banner, including `ssh-keyscan`, time out on this shared port. Use the host's normal SSH port for those tools.

HTTPS retains local SNI routing and TLS passthrough to B, including certificate validation. Plain HTTP on port 443 goes to Caddy's HTTP listener on port 80. The port 80 catch-all redirects every hostname to HTTPS on port 443, including unknown names. It preserves the path and query and removes any incoming Host port. Unknown names can still fail the TLS handshake after redirection.

When replacing an external splitter, preserve the Caddy configuration and data directories. Move the host mappings for ports 80 and 443 to Caddy Full. Add `SSH_SPLITTER: "true"` and the `extra_hosts` mapping to its service. Stop the old splitter before starting Caddy Full with those host mappings. The two containers cannot bind the same host ports simultaneously.

See the upstream [SSH matcher](https://github.com/mholt/caddy-l4/blob/v0.1.2/docs/matchers/ssh.md) and [HTTP matcher](https://github.com/mholt/caddy-l4/blob/v0.1.2/docs/matchers/http.md) documentation.

## Configuration

- `SSH_SPLITTER`: `true` enables SSH, HTTP, and HTTPS on TCP 443. The default is `false`.
- `SSH_PROXY`: SSH destination as `host:port`, with `host.docker.internal:22` as the default. Used only when splitting is enabled.
- `FALLBACK_PROXY`: next machine as `host:port`, without a URL scheme. An empty value disables forwarding.
- `HTTPS_PORT`: optional override for the local Caddy HTTPS port. Leave it unset for the standard deployment. It defaults to `8443` when fallback or SSH splitting is enabled, and `443` otherwise. Layer 4 reserves TCP 443 when either feature is enabled.
- `TLS_ALPN_ONLY`: `true` selects ACME validation over TLS on port 443. It defaults to `true`, including when the value is empty. Set it to `false` to also enable HTTP validation on port 80.
- `LOCAL_DOMAINS`: space-separated domains from hand-written `conf.d` sites that A must handle locally. This does not create sites or certificates.
- `CADDY_INSTANCE`: optional label scope when several proxies use one Docker daemon. Matching services require `caddy.instance` with the same value.
- `ACME_CA`: optional ACME directory URL for a staging or test certificate authority.
- `ACME_CA_ROOT`: optional trusted PEM certificate path for a private ACME endpoint.
- `PUID` and `PGID`: optional numeric runtime user and group IDs. The entrypoint grants access to the Docker socket group.
- `UMASK`: optional file creation mask, such as `022`.
- `TZ`: optional timezone, such as `America/New_York`.


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

The examples mount two host directories. Relative paths start beside the Compose file. A and B each keep their own directories.

`./caddy-config:/etc/caddy` stores Caddy configuration. It contains the managed `Caddyfile`, generated routes in `default.d/default.caddy`, and your custom snippets in `conf.d/`. Startup replaces the managed files, and Docker events regenerate the routes. Keep manual changes in `conf.d/`.

`./caddy-data:/data` stores Caddy's persistent state under `/data/caddy`. This includes certificates, their private keys, ACME account keys, and local certificate authorities when used. It does not store your application's files or database.

Preserve and back up both directories when updating containers. Protect the data backup because it contains private keys. Losing `/data` requires new certificates and can trigger certificate authority issuance limits. Losing `/etc/caddy` removes custom snippets, but Docker labels can regenerate the managed routes. An `/etc/caddy` mount alone does not preserve certificates.

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

See [verification details](VERIFICATION.md). Use `docker build` for local builds.

## Publication

Every push to `main` starts the [Docker workflow](.github/workflows/docker-publish.yml). It builds one `linux/amd64` image and runs the integration tests before publication. It then publishes that tested image only to GHCR.

GHCR receives `ghcr.io/yzard/caddy-full:YYYYMMDD` and `ghcr.io/yzard/caddy-full:latest`. `YYYYMMDD` uses the date in `America/New_York` when the job selects its tags. Another successful run on the same date replaces that date's tag. Each successful publication updates `latest`. The workflow compares both remote digests after publication.

GHCR authentication uses the temporary `GITHUB_TOKEN` that GitHub creates automatically for each job, with `packages: write` permission. No manually configured repository secret is required. The workflow does not store or use Docker Hub publishing credentials.

The workflow serializes publication runs to prevent concurrent tag updates. It publishes the dated tag before updating `latest`. Manual runs are also available through `workflow_dispatch` on `main`. The old `main` image tag is no longer updated.

Docker Hub publication remains separate. On a machine with Docker Hub login credentials, run this command from the repository root:

```sh
./build.sh
```

The script builds and pushes `zhuoyin/caddy-full:YYYYMMDD` and `zhuoyin/caddy-full:latest` using the local Docker login. Its date uses the local machine's timezone. GitHub Actions does not publish these Docker Hub tags. Docker Hub stays at the last manual release until you run `build.sh` again.

## References

[Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https) describes certificate validation. [Caddy Layer 4](https://github.com/mholt/caddy-l4) supplies SNI routing and TLS passthrough.
