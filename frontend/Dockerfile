ARG RELEASE_VERSION=4.9.10-rc.1
FROM node:22-alpine AS build
ARG RELEASE_VERSION
WORKDIR /app
COPY package.json package-lock.json* ./
RUN node -e 'if (require("./package.json").version !== process.env.RELEASE_VERSION) throw Error("frontend source/version mismatch")'
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.30.6-alpine
ARG RELEASE_COMMIT=unbound
ARG RELEASE_VERSION
LABEL org.opencontainers.image.revision=${RELEASE_COMMIT}
LABEL org.opencontainers.image.version=${RELEASE_VERSION}
RUN apk del nginx-module-xslt nginx-module-image-filter nginx-module-geoip nginx-module-njs nginx-module-acme \
    && apk upgrade --no-cache
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80

