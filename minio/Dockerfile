# MinIO 官方已不再在 Docker Hub / quay.io 发布镜像（minio/minio 拉不到），
# 这里从官方源码仓库的固定版本构建，不依赖第三方镜像。首次构建约需 5–10 分钟。
FROM golang:1.24-alpine AS build
RUN apk add --no-cache git
ARG MINIO_RELEASE=RELEASE.2025-09-07T16-13-09Z
ARG MINIO_VERSION=2025-09-07T16:13:09Z
RUN git clone --depth 1 --branch ${MINIO_RELEASE} https://github.com/minio/minio.git /src
WORKDIR /src
RUN CGO_ENABLED=0 go build -trimpath -tags kqueue \
    -ldflags "-s -w -X github.com/minio/minio/cmd.Version=${MINIO_VERSION} -X github.com/minio/minio/cmd.ReleaseTag=${MINIO_RELEASE}" \
    -o /minio .

FROM alpine:3.21.3
RUN apk add --no-cache ca-certificates
COPY --from=build /minio /usr/bin/minio
EXPOSE 9000
ENTRYPOINT ["minio"]
