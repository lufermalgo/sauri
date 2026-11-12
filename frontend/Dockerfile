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

FROM nginx:stable-alpine@sha256:583b7f2fce1cdb8da5ad5c39ebd3c33b98b87d493190e548bdee1fa8c619c311
RUN rm -rf /usr/share/nginx/html/*
COPY --from=build /app/frontend/dist/ /usr/share/nginx/html/
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
