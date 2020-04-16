dockergen: docker-gen -watch -wait 500ms:2s -only-exposed /code/templates/Caddyfile.tmpl /etc/caddy/default.d/default.caddy
caddy: caddy start --config /etc/caddy/Caddyfile --watch
