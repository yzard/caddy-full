# Caddy 2 Gen (docker-gen + conf.d)

This is caddy docker with capability of:
- share both ssh and https traffic in same port (use layer4)
- reverse proxy with docker-gen support
- fallback proxy

docker-gen output with hand-written Caddy snippets.

It gives you a drop-in Caddy reverse proxy that:
- reads Docker labels and renders `/etc/caddy/default.d/default.caddy`
- loads both generated config and `conf.d/*.caddy`
- supports multiple domains, path-based routing, and optional ACME email

[Docker Hub](https://hub.docker.com/repository/docker/siemko8/caddy-full)

## How it works

- `docker-gen` watches Docker and renders `templates/Caddyfile.tmpl`
  into `/etc/caddy/default.d/default.caddy`
- Caddy loads `/etc/caddy/Caddyfile`, which imports:
  - `/etc/caddy/default.d/*` (generated)
  - `/etc/caddy/conf.d/*` (your custom snippets)

## Environment variables

- `FALLBACK_PROXY`: catch-all upstream (e.g. `fallback:8080`) for requests
  that do not match any generated site (HTTPS only; HTTP always redirects)
- `SSH_HOST`: optional SSH target for port 443 passthrough (e.g. `ssh:22`)
- `PUID`/`PGID`: run the container as this user/group (e.g. `1000`/`1000`)
- `UMASK`: file creation mask (e.g. `022`)
- `TZ`: timezone (e.g. `UTC` or `America/Los_Angeles`)

## Quick start (demo stack)

Run the demo stack in `sample/docker-compose.yml`:

```bash
docker-compose -f sample/docker-compose.yml up --build
```

Override runtime permissions/timezone (optional):

```bash
PUID=1000 PGID=1000 UMASK=022 TZ=UTC \
  docker-compose -f sample/docker-compose.yml up --build
```

The proxy expects a Docker socket mounted read-only at `/tmp/docker.sock` and
persists state under `/etc/caddy` (see `./sample/volume` in the compose file).

Optional SSH passthrough:

```bash
SSH_HOST=ssh.example.com:22 \
  docker-compose -f sample/docker-compose.yml up --build
```

## Label reference

Use `caddy.N.*` labels on your service containers:

- `caddy.N.domain` domain name(s), space separated, no scheme
- `caddy.N.port` container port to proxy to
- `caddy.N.paths` comma-separated `path:port` pairs
- `caddy.N.tls` ACME email for certificate management

`N` can be `0`, `1`, `2`, … for multiple site blocks per container.

## Examples

Basic domain + port (from `sample/docker-compose.yml`):

```yaml
services:
  whoami:
    image: "katacoda/docker-http-server:v1"
    labels:
      caddy.0.domain: test1.localhost
      caddy.0.port: 253
      caddy.1.domain: test2.localhost:234
      caddy.1.port: 2314
```

Path-based routing (from `sample/docker-compose.yml`):

```yaml
services:
  whoami2:
    image: "katacoda/docker-http-server:v2"
    labels:
      caddy.0.domain: test3.localhost
      caddy.0.paths: foo:1234,bar:324
```

Add TLS email (optional):

```yaml
labels:
  caddy.0.tls: admin@example.com
```

## Add custom Caddy config

Mount or edit files under `./sample/volume/conf.d`:

```caddyfile
example.internal {
    respond "hello from conf.d"
}
```

## Persist state (certs, config)

Mount a volume to `/etc/caddy`:

```
./sample/volume:/etc/caddy
```
