ARG BASE_IMAGE=debian:trixie-slim
FROM ${BASE_IMAGE}

# One Debian 13 toolchain for compositor checks, live-build, and QEMU.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential meson ninja-build pkg-config libwlroots-0.18-dev \
    libwayland-dev wayland-protocols libxkbcommon-dev libxcb1-dev \
    python3 python3-pil foot wtype grim wlr-randr fonts-dejavu-core dbus-daemon \
    live-build debootstrap rsync imagemagick ca-certificates curl \
    qemu-system-x86 qemu-utils xorriso squashfs-tools dosfstools mtools \
    && if [ "$(dpkg --print-architecture)" = amd64 ]; then \
         apt-get install -y --no-install-recommends grub-pc-bin grub-efi-amd64-bin isolinux syslinux-common; \
       fi \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    qemu-system-arm qemu-efi-aarch64 \
    && if [ "$(dpkg --print-architecture)" = arm64 ]; then \
         apt-get install -y --no-install-recommends grub-efi-arm64-bin; \
       fi \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    isolinux syslinux-common \
    && if [ "$(dpkg --print-architecture)" = amd64 ]; then \
         apt-get install -y --no-install-recommends grub-efi-ia32-bin; \
       fi \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=C.UTF-8
WORKDIR /work
