caddy: caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
dockergen: docker-gen -watch -wait 500ms:2s -only-exposed -notify "caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile" /code/templates/Caddyfile.tmpl /etc/caddy/default.d/default.caddy
