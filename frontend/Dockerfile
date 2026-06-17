# syntax=docker/dockerfile:1
# AI-Native Finance Platform — frontend (React + Vite, served by nginx)

# --- build stage ---------------------------------------------------------
FROM node:20-slim AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# Built app calls the API with relative paths (VITE_API_URL defaults to ''),
# so nginx (below) reverse-proxies /agents, /jobs, /approvals, /health.
RUN npm run build

# --- runtime stage -------------------------------------------------------
FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
