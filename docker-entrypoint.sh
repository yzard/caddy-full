#!/bin/sh

set -o errexit
set -o nounset

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

        if ! grep -q '^caddy:' /etc/passwd; then
            adduser -D -H -u "${PUID}" -G "${group_name}" caddy
        fi

        if [ -S /tmp/docker.sock ]; then
            DOCKER_GID="$(stat -c '%g' /tmp/docker.sock)"
            docker_group="$(awk -F: -v gid="${DOCKER_GID}" '$3==gid{print $1}' /etc/group)"
            if [ -n "${docker_group}" ]; then
                addgroup caddy "${docker_group}"
            fi
        fi
    fi

    chown -R "${PUID}:${PGID}" /etc/caddy /data 2>/dev/null || true
fi

if [ -n "${SSH_HOST:-}" ]; then
    SSH_BLOCK_FILE="/tmp/ssh_block.caddy"
    cat <<EOF > "${SSH_BLOCK_FILE}"
            route {
                proxy ${SSH_HOST}
            }
EOF
    sed "/{{SSH_BLOCK}}/{
        r ${SSH_BLOCK_FILE}
        d
    }" /code/caddy/Caddyfile.ssh > /etc/caddy/Caddyfile
else
    cp /code/caddy/Caddyfile /etc/caddy/Caddyfile
fi

mkdir -p /etc/caddy/conf.d

mkdir -p /etc/caddy/default.d
docker-gen -only-exposed /code/templates/Caddyfile.tmpl /etc/caddy/default.d/default.caddy

echo "first execution success"

# Execute passed command:
if [ -n "${PUID:-}" ] || [ -n "${PGID:-}" ]; then
    if [ "${PUID:-1000}" -ne 0 ] || [ "${PGID:-1000}" -ne 0 ]; then
        exec su-exec caddy "$@"
    fi
fi

exec "$@"
