# Two-machine quick start

Use [the complete A and B YAML examples](TWO_TIER_SETUP.md). They use `ghcr.io/yzard/caddy-full:latest` from GitHub Container Registry (GHCR) and include service labels, network connections, and persistent certificate storage. No local build is required.

For the repository sample files, replace the example domains and emails first. On B, run this command from the repository root:

```sh
docker compose -f sample/two-tier-host2-docker-compose.yml up -d
```

On A, set B's LAN address and start the proxy:

```sh
FALLBACK_HOST=192.168.1.20 docker compose -f sample/two-tier-host1-docker-compose.yml up -d
```

Both proxies use TLS-ALPN validation through TCP 443. Service labels stay on the machine that runs each service. Unknown domains without certificates fail the TLS handshake.
