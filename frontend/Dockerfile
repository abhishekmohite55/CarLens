# Frontend image (platform step 6.5, docs/platform/06-admin.md §7): build both apps with Node, serve them with nginx.
# Build context is frontend/ (frontend/.dockerignore keeps node_modules and old builds out).

# 1. Build: same Node major as the laptop; npm ci installs exactly what package-lock.json lists.
FROM node:24.20.0-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts # hardening S12: no package install scripts
COPY . .
RUN npm run build

# 2. Serve: only nginx and the built files; no Node, no source, no node_modules in the final image.
# Hardening S15: NGINX's own non-root build of the same version (user 101, port 8080).
FROM nginxinc/nginx-unprivileged:1.30.6-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx-headers.conf /etc/nginx/carlens-headers.conf
COPY nginx-csp.conf /etc/nginx/carlens-csp.conf
COPY --from=build /app/dist /usr/share/nginx/html
