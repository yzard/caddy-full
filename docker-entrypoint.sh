#!/bin/sh

set -o errexit
set -o nounset

# A fallback always passes the original TLS connection to the next host.
if [ -n "${FALLBACK_PROXY:-}" ]; then
    HTTPS_PORT="${HTTPS_PORT:-8443}"
else
    HTTPS_PORT="${HTTPS_PORT:-443}"
fi
case "$HTTPS_PORT" in
    *[!0-9]*|'') echo "HTTPS_PORT must be a port number" >&2; exit 1 ;;
esac
if [ "$HTTPS_PORT" -lt 1 ] || [ "$HTTPS_PORT" -gt 65535 ] || [ "$HTTPS_PORT" -eq 80 ]; then
    echo "HTTPS_PORT must be between 1 and 65535 and different from 80" >&2
    exit 1
fi
if [ -n "${FALLBACK_PROXY:-}" ] && [ "$HTTPS_PORT" -eq 443 ]; then
    echo "FALLBACK_PROXY reserves port 443. Set HTTPS_PORT=8443 or leave it unset." >&2
    exit 1
fi
case "${FALLBACK_PROXY:-}" in
    *://*|*[[:space:]]*) echo "FALLBACK_PROXY must be a host:port address without a scheme or whitespace" >&2; exit 1 ;;
esac
TLS_ALPN_ONLY="${TLS_ALPN_ONLY:-true}"
case "$TLS_ALPN_ONLY" in
    true|false) ;;
    *) echo "TLS_ALPN_ONLY must be true or false" >&2; exit 1 ;;
esac
export HTTPS_PORT TLS_ALPN_ONLY

# Optional runtime settings (host-friendly permissions, TZ, umask).
if [ -n "${TZ:-}" ] && [ -e "/usr/share/zoneinfo/${TZ}" ]; then
    ln -snf "/usr/share/zoneinfo/${TZ}" /etc/localtime
    echo "${TZ}" > /etc/timezone
fi

if [ -n "${UMASK:-}" ]; then
    umask "${UMASK}"
fi

# Ensure Caddy data dir exists for storage (certs, etc.).
mkdir -p /data

# Create initial configuration:
mkdir -p /etc/caddy
if [ -n "${PUID:-}" ] || [ -n "${PGID:-}" ]; then
    PUID="${PUID:-1000}"
    PGID="${PGID:-1000}"

    case "${PUID}:${PGID}" in
        *[!0-9:]*|:*|*:) echo "PUID and PGID must be numeric" >&2; exit 1 ;;
    esac

    if [ "${PUID}" -ne 0 ] || [ "${PGID}" -ne 0 ]; then
        if [ -S /tmp/docker.sock ]; then
            DOCKER_GID="$(stat -c '%g' /tmp/docker.sock)"
            if ! awk -F: -v gid="${DOCKER_GID}" '$3==gid{found=1} END{exit !found}' /etc/group; then
                addgroup -g "${DOCKER_GID}" docker
            fi
        fi

        group_name="$(awk -F: -v gid="${PGID}" '$3==gid{print $1}' /etc/group)"
        if [ -z "${group_name}" ]; then
            addgroup -g "${PGID}" caddy
            group_name="caddy"
        fi

        runtime_user="$(awk -F: -v uid="${PUID}" '$3==uid{print $1; exit}' /etc/passwd)"
        if [ -z "$runtime_user" ]; then
            adduser -D -H -u "${PUID}" -G "${group_name}" caddy
            runtime_user=caddy
        fi
        # su-exec retains supplementary groups only without an explicit group.
        awk -F: -v OFS=: -v uid="$PUID" -v gid="$PGID" '{if ($3==uid) $4=gid; print}' /etc/passwd > /etc/passwd.caddy
        cat /etc/passwd.caddy > /etc/passwd
        rm /etc/passwd.caddy

        if [ -S /tmp/docker.sock ]; then
            DOCKER_GID="$(stat -c '%g' /tmp/docker.sock)"
            docker_group="$(awk -F: -v gid="${DOCKER_GID}" '$3==gid{print $1}' /etc/group)"
            if [ -n "${docker_group}" ]; then
                addgroup "$runtime_user" "${docker_group}"
            fi
        fi
    fi

fi

cp /code/caddy/Caddyfile /etc/caddy/Caddyfile

mkdir -p /etc/caddy/conf.d

mkdir -p /etc/caddy/default.d
docker-gen -only-exposed /code/templates/Caddyfile.tmpl /etc/caddy/default.d/default.caddy
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
# Generated files must remain writable after the privilege drop.
if [ -n "${PUID:-}" ] || [ -n "${PGID:-}" ]; then
    chown -R "${PUID}:${PGID}" /etc/caddy /data
fi

echo "first execution success"

# Execute passed command:
if [ -n "${PUID:-}" ] || [ -n "${PGID:-}" ]; then
    if [ "${PUID:-1000}" -ne 0 ] || [ "${PGID:-1000}" -ne 0 ]; then
        exec su-exec "$runtime_user" "$@"
    fi
fi

exec "$@"
