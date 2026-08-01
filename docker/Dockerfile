# Pure redroid image + vendor overlay only.
# Context prepared by scripts/build-image.sh (must contain vendor/).
# Future microG/Magisk variants should extend this Dockerfile or add COPY lines
# for system/ when EXTRA_OVERLAY provides them.
ARG BASE_IMAGE=redroid/redroid:13.0.0_64only-latest
FROM ${BASE_IMAGE}
COPY vendor/ /vendor/
