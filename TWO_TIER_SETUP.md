# Deploy on A and B

A receives public TCP 443 traffic. B receives forwarded TLS connections from A. Both machines run Caddy Full and discover labels from their own Docker daemon. The examples pull `ghcr.io/yzard/caddy-full:latest` from GitHub Container Registry (GHCR). Neither machine needs the source repository or a local image build.

```text
Internet TCP 443 -> A
                    |-- local domain -> A's Caddy -> A's service
                    `-- other domain -> B's Caddy -> B's service
                                                 `-> TLS failure for an unknown name
```

## Prepare the network

Point `a.example.com` and `b.example.com` to the public IP of A's router. Forward public TCP 443 to A's TCP 443. For HTTP redirects, also forward TCP 80 to A. Certificate validation does not require TCP 80 in this setup.

Give B a stable LAN address, such as `192.168.1.20`. Allow A to reach B on TCP 443. Allow outbound HTTPS from both machines. Keep A and B's clocks synchronized.

## Machine A

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

A selects internal port 8443 automatically when `FALLBACK_PROXY` is set. You do not need to set `HTTPS_PORT`. Port 8443 stays inside the container. The public port 443 reads the requested domain before forwarding the original TLS connection.

A also enables SSH on TCP 443 through `SSH_SPLITTER=true`. The `extra_hosts` entry lets Caddy reach A's host SSH server at `host.docker.internal:22`. SSH stays on A, while HTTPS continues to use the domain routes. Set `SSH_SPLITTER` to `false` to disable SSH splitting.

Connect through the shared port with `ssh -p 443 your-user@a.example.com`. If A uses another SSH port, set `SSH_PROXY` to `host.docker.internal:PORT`. See [SSH splitting details](README.md#ssh-on-the-https-port) for requirements and migration from an external splitter.

## Machine B

Save this file as `compose.yaml` in a deployment directory on B. Replace the domain and email with your values. Do not set `FALLBACK_PROXY` on B.

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

The router does not forward public traffic directly to B. B publishes TCP 443 on its LAN address so A can reach it.

## Start the services

On each machine, run this command beside its `compose.yaml`:

```sh
docker compose up -d
```

After each push to `main`, a successful GitHub Actions build and test run publishes the new GHCR `latest` image. Running containers do not update automatically.

`pull_policy: always` makes Compose pull the current proxy image when you run `docker compose up -d`. After publication, run that command on A and B to apply the newer image. Existing certificate and configuration directories remain mounted.

The `caddy-config` directory stores generated configuration and custom snippets. The `caddy-data` directory stores certificates, private keys, and ACME accounts. Each machine keeps its own directories. See [directory details](README.md#generated-files-and-state) before changing or removing these mounts.

On B, read the certificate logs:

```sh
docker compose logs -f rp2
```

On A, read the forwarding logs:

```sh
docker compose logs -f rp1
```

B sends the certificate request to the certificate authority. The authority connects to `b.example.com:443`, which reaches A. A has no local label for that domain, so it forwards the TLS validation connection to B. B completes validation and stores its certificate under `/data/caddy`. Renewal uses the same route.

`TLS_ALPN_ONLY` selects certificate validation methods. It does not select a gateway role. It defaults to `true` on both machines, so these YAML files omit it. B needs the TLS validation path because A does not forward HTTP challenge requests to B. Setting it explicitly to `false` also enables HTTP validation, which can fail before Caddy tries TLS validation.

A and B do not share certificates, Docker sockets, or Docker networks. The Docker network called `proxy` exists independently on each machine.

## Add your own service

Replace the sample Nginx container with your application. Set `caddy.0.port` to its internal listening port. If its image does not declare that port, add Compose `expose`:

```yaml
expose:
  - "8080"
labels:
  caddy.0.domain: new.example.com
  caddy.0.port: "8080"
```

Create a DNS record for the new name, or use an existing wildcard DNS record. Add B's service labels only on B. A does not need a copy. Docker events update both routing tables automatically.

Keep each domain on one machine. If both declare the same name, A takes priority and B cannot complete new validation for that name through A. A local application error does not trigger fallback.

## Existing installations

This implementation replaces the previous HTTP fallback proposal with TLS passthrough. If A has `FALLBACK_PROXY` and `HTTPS_PORT=443`, remove `HTTPS_PORT` or change it to `8443`. The entrypoint rejects that port conflict.

The base Caddyfile and generated output are managed files. Preserve custom site blocks in `conf.d`. Add their local domain names to `LOCAL_DOMAINS` on A. The old `layer4.d` output is no longer loaded.

Preserve the existing `/data` volume before recreating containers. The old examples mounted only `/etc/caddy`, which does not contain Caddy's default certificate storage.

## Failure behavior

An unknown domain reaches B and fails the TLS handshake if B has no matching certificate. No public certificate is requested for that unknown name. If B is down, its forwarded TLS connections fail. A's own domains still use A's local services.

A known domain with a missing application path returns the application's response. A known domain with an unavailable backend returns a proxy error. Neither case triggers another machine lookup.
