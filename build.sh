#!/bin/sh

set -x

version=`date +'%Y%m%d'`

docker buildx build -t zhuoyin/caddy-full:${version} .
docker tag zhuoyin/caddy-full:${version} zhuoyin/caddy-full:latest

docker image push zhuoyin/caddy-full:${version}
docker image push zhuoyin/caddy-full:latest
