# redroid-mesa

Build **Android Mesa** and publish a **pure Redroid A13** image with Intel host-GPU
support (Arrow Lake `0x7d67`, Mesa **26.1.5**).

Image tags: `a13-26.1.5`, `a13`, `latest`.

## Layout

```
scripts/build.sh         one entry: Mesa → vendor stage → docker image
scripts/install-deps.sh  host packages (Fedora / Ubuntu CI)
variants/a13/            BASE_IMAGE + MESA_TAG
docker/Dockerfile        FROM redroid + COPY /vendor
compose/                 runtime (+ scrcpy-web)
.github/workflows        GHCR publish
```

## Local

```bash
cd ~/Workspace/redroid-mesa
chmod +x scripts/*.sh
./scripts/build.sh
# → redroid-mesa:a13-26.1.5 / :a13 / :latest

mkdir -p data
IMAGE=redroid-mesa:a13-26.1.5 docker compose -f compose/docker-compose.yml up -d
# http://127.0.0.1:8000
```
