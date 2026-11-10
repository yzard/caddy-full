# Fallback behavior

`FALLBACK_PROXY` enables TLS passthrough. A reads the requested domain before the TLS handshake completes. Known local domains use A's local Caddy HTTPS port. Other domains go to the configured next machine.

The earlier HTTP fallback proposal cannot provide this certificate behavior. HTTP routing starts after the TLS handshake, so it cannot handle a new B-only domain without a certificate on A.

With fallback, `HTTPS_PORT` defaults to `8443`. Without fallback, it defaults to `443`. Setting both fallback and `HTTPS_PORT=443` fails at startup because the listeners conflict.

Use [the deployment guide](TWO_TIER_SETUP.md) for complete A and B examples. Unknown domains without certificates fail the TLS handshake. They do not return an HTTPS 404.
