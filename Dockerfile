ARG DOCKER_GEN_VERSION="0.16.1"
ARG FOREGO_VERSION="v0.18.2"
ARG GO_VERSION="1.25.5"
ARG CADDY_VERSION="2.10.2"


# building forego
FROM golang:${GO_VERSION} AS forego
ARG FOREGO_VERSION
RUN git clone https://github.com/nginx-proxy/forego/ \
   && cd /go/forego \
   && git -c advice.detachedHead=false checkout $FOREGO_VERSION \
   && go mod download \
   && CGO_ENABLED=0 GOOS=linux go build -o forego . \
   && go clean -cache \
   && mv forego /usr/local/bin/ \
   && cd - \
   && rm -rf /go/forego

# building docker-gen
FROM golang:${GO_VERSION} AS dockergen
ARG DOCKER_GEN_VERSION
RUN git clone https://github.com/nginx-proxy/docker-gen \
   && cd /go/docker-gen \
   && git -c advice.detachedHead=false checkout $DOCKER_GEN_VERSION \
   && go mod download \
   && CGO_ENABLED=0 GOOS=linux go build -ldflags "-X main.buildVersion=${DOCKER_GEN_VERSION}" ./cmd/docker-gen \
   && go clean -cache \
   && mv docker-gen /usr/local/bin/ \
   && cd - \
   && rm -rf /go/docker-gen

# building caddy with brotli and layer4 support
FROM caddy:${CADDY_VERSION}-builder-alpine AS caddy_bundle
ARG CADDY_VERSION
RUN xcaddy build v${CADDY_VERSION} \
    --with github.com/ueffel/caddy-brotli@2a080feb1c91d56672c2b9d97ffed086b960582f \
    --with github.com/mholt/caddy-l4@1a3490ef786a8fd93128d55aed1999930b7c0586


# start build actual image
FROM alpine:3.22 AS main

COPY --from=caddy_bundle /usr/bin/caddy /usr/bin/caddy
COPY --from=forego /usr/local/bin/forego /usr/local/bin/forego
COPY --from=dockergen /usr/local/bin/docker-gen /usr/local/bin/docker-gen

ENV CADDYPATH="/etc/caddy"
ENV XDG_DATA_HOME="/data"
ENV XDG_CONFIG_HOME="/etc/caddy"
ENV DOCKER_HOST="unix:///tmp/docker.sock"

RUN apk --no-cache add bash su-exec tzdata ca-certificates

EXPOSE 80 443 2015
VOLUME /etc/caddy /data

COPY Procfile docker-entrypoint.sh /code/
COPY caddy /code/caddy
COPY templates /code/templates
WORKDIR /code


ENTRYPOINT ["sh", "/code/docker-entrypoint.sh"]
CMD ["/usr/local/bin/forego", "start", "-r"]
