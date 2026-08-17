# Build the SPA, serve it with nginx (proxies /dashboard and /api to the
# backend container -- see nginx.conf).
FROM node:22-alpine AS build
WORKDIR /build
# ponytail: no package-lock.json in the repo, so npm install (not ci);
# commit a lockfile and switch to `npm ci` for reproducible builds.
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html
EXPOSE 80
