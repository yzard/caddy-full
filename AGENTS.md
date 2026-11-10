# Repository Guidelines

## Project Structure & Module Organization
- `Dockerfile` builds the runtime image (Caddy + docker-gen + forego).
- `docker-entrypoint.sh` bootstraps `/etc/caddy`, generates `default.caddy`, then launches forego.
- `templates/Caddyfile.tmpl` is the docker-gen template for dynamic Caddyfile output.
- `caddy/Caddyfile` provides the base Caddyfile loaded into `/etc/caddy`.
- `sample/volume/` is a local example volume for Caddy data (`conf.d`, `default.d`).
- `sample/docker-compose.yml` provides a local demo stack with labeled services.

## Build, Test, and Development Commands
- `docker build -t caddy-full .` builds the image locally.
- `docker-compose -f sample/docker-compose.yml up --build` runs the demo stack.
- `./build.sh` builds and pushes versioned and `latest` images (uses `docker buildx build`).

## Coding Style & Naming Conventions
- Shell scripts use POSIX `sh`; keep them minimal and `set -o errexit`/`nounset` friendly.
- YAML uses 2-space indentation; keep keys aligned with existing style.
- Template files follow Caddyfile syntax; keep placeholder names descriptive (e.g., `caddy.0.domain`).

## Testing Guidelines
- No automated test suite is present.
- Validate changes by running the compose stack and confirming `/etc/caddy/default.d/default.caddy` renders as expected.

## Commit & Pull Request Guidelines
- Git history only contains `initial commit`; no convention is established yet.
- Use short, imperative commit subjects (e.g., "Add docker-gen template guard").
- PRs should include a concise summary, testing notes (commands run), and any Caddyfile output samples when template logic changes.

## Configuration & Operational Notes
- The container expects a Docker socket mounted read-only at `/tmp/docker.sock`.
- Persist Caddy state by mounting `./sample/volume` to `/etc/caddy` (see `sample/docker-compose.yml`).
- Labels drive routing; keep examples in `README.md` and `sample/docker-compose.yml` in sync.
