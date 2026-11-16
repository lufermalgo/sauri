FROM node:22-alpine@sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY extension/package.json extension/package.json
COPY frontend/package.json frontend/package.json
COPY packages/shared-types/package.json packages/shared-types/package.json
# The root prepare hook configures Git, which is deliberately absent here.
# Install workspace dependencies with their lifecycle scripts; omit only root prepare.
RUN npm pkg delete scripts.prepare && npm ci
COPY frontend/ frontend/
COPY packages/shared-types/ packages/shared-types/
RUN VITE_API_BASE_URL='' npm run build --workspace frontend
# Hash of the inline theme bootstrap emitted by Vite; the portal CSP allows exactly that script.
COPY scripts/platform/inline-script-hash.mjs /tmp/inline-script-hash.mjs
RUN node /tmp/inline-script-hash.mjs frontend/dist/index.html > /tmp/inline-script.hash

FROM nginx:stable-alpine@sha256:583b7f2fce1cdb8da5ad5c39ebd3c33b98b87d493190e548bdee1fa8c619c311
RUN rm -rf /usr/share/nginx/html/* /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/dist/ /usr/share/nginx/html/
# The entrypoint renders these templates into /etc/nginx/conf.d at start (only ${SAURI_*} variables).
COPY frontend/nginx.conf /etc/nginx/templates/default.conf.template
COPY frontend/security-headers.conf /etc/nginx/templates/snippets/security-headers.conf.template
COPY --from=build /tmp/inline-script.hash /tmp/inline-script.hash
RUN sed -i "s|__INLINE_SCRIPT_HASH__|$(cat /tmp/inline-script.hash)|" \
        /etc/nginx/templates/snippets/security-headers.conf.template \
    && rm /tmp/inline-script.hash
# Origin of the object store the browser loads signed media/thumbnails from (OBJECT_STORE_PUBLIC_ENDPOINT).
ENV NGINX_ENVSUBST_FILTER=^SAURI_ \
    SAURI_OBJECT_STORE_ORIGIN=http://localhost:9000
EXPOSE 80
