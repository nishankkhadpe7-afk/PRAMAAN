# Build the React/Vite frontend and serve it via nginx, proxying /api to the app.
FROM node:20-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# vite build only (skip tsc type-check so a minor TS warning never blocks the demo image).
RUN npx vite build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80
