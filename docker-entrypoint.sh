#!/bin/sh

set -o errexit
set -o nounset

SSH_SPLITTER="${SSH_SPLITTER:-false}"
case "$SSH_SPLITTER" in
    true|false) ;;
    *) echo "SSH_SPLITTER must be true or false" >&2; exit 1 ;;
esac
SSH_PROXY="${SSH_PROXY:-host.docker.internal:22}"
if [ "$SSH_SPLITTER" = true ]; then
    case "$SSH_PROXY" in
        *[[:space:]]*) echo "SSH_PROXY must not contain whitespace" >&2; exit 1 ;;
    esac
    if ! printf '%s\n' "$SSH_PROXY" | awk '
        /^[a-zA-Z0-9._-]+:[0-9]+$/ || /^\[[0-9a-fA-F:]+\]:[0-9]+$/ {
            sub(/^.*:/, ""); if ($0 >= 1 && $0 <= 65535) valid=1
        }
        END { exit !valid }
    '; then
        echo "SSH_PROXY must be a host:port address with a port between 1 and 65535" >&2
        exit 1
    fi
fi

if [ -n "${HTTPS_PORT:-}" ]; then
    case "$HTTPS_PORT" in
        *[!0-9]*) echo "HTTPS_PORT must be a port number" >&2; exit 1 ;;
    esac
    if [ "$HTTPS_PORT" -lt 1 ] || [ "$HTTPS_PORT" -gt 65535 ] || [ "$HTTPS_PORT" -eq 80 ]; then
        echo "HTTPS_PORT must be between 1 and 65535 and different from 80" >&2
        exit 1
    fi
    if { [ -n "${FALLBACK_PROXY:-}" ] || [ "$SSH_SPLITTER" = true ]; } && [ "$HTTPS_PORT" -eq 443 ]; then
        echo "Layer 4 reserves port 443. Leave HTTPS_PORT unset or use a different internal port." >&2
        exit 1
    fi
fi
case "${FALLBACK_PROXY:-}" in
    *://*|*[[:space:]]*) echo "FALLBACK_PROXY must be a host:port address without a scheme or whitespace" >&2; exit 1 ;;
esac
TLS_ALPN_ONLY="${TLS_ALPN_ONLY:-true}"
case "$TLS_ALPN_ONLY" in
    true|false) ;;
    *) echo "TLS_ALPN_ONLY must be true or false" >&2; exit 1 ;;
esac
export HTTPS_PORT TLS_ALPN_ONLY SSH_SPLITTER SSH_PROXY

# Docker bind-mounts this container's hostname file from its metadata directory.
# Use the ID from that mount so a custom hostname cannot select another container.
CADDY_SELF_ID="$(awk '$5 == "/etc/hostname" && $4 ~ /\/containers\/[0-9a-f]+\/hostname$/ {
    count = split($4, parts, "/")
    print parts[count - 1]
}' /proc/self/mountinfo)"
export CADDY_SELF_ID

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
# Docker can start the entrypoint before it lists this container as running.
# Render to a fresh file so a failed render cannot reuse an old configuration.
generated_dir="$(mktemp -d)"
trap 'rm -rf "$generated_dir"' EXIT
for attempt in 1 2 3 4 5; do
    if docker-gen -only-exposed /code/templates/Caddyfile.tmpl "$generated_dir/default.caddy" &&
        [ -s "$generated_dir/default.caddy" ]; then
        break
    fi
    if [ "$attempt" -eq 5 ]; then
        echo "Failed to generate the Caddy configuration" >&2
        exit 1
    fi
    sleep 1
done
mv "$generated_dir/default.caddy" /etc/caddy/default.d/default.caddy
rmdir "$generated_dir"
trap - EXIT
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
