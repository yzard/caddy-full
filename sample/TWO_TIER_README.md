# Two-machine samples

Use `two-tier-host1-docker-compose.yml` on A and `two-tier-host2-docker-compose.yml` on B. Replace example domains and emails before starting either stack. Set `FALLBACK_HOST` to B's LAN address on A.

The files pull `zhuoyin/caddy-full:latest` from Docker Hub. `pull_policy: always` requests the current image when Compose starts the stack. No local build is required. They persist certificates in `/data` and custom snippets in `/etc/caddy`.

See [the deployment guide](../TWO_TIER_SETUP.md) for network requirements and complete standalone YAML examples. See [verification details](../VERIFICATION.md) for the isolated test command.
