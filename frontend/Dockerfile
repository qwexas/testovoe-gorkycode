# syntax=docker/dockerfile:1.7
# Фронтенд «Горького»: Next.js standalone-сборка, слушает 3000.

ARG NODE_VERSION=24-alpine
ARG PNPM_VERSION=12.15.0

FROM node:${NODE_VERSION} AS base
ARG PNPM_VERSION
ENV NEXT_TELEMETRY_DISABLED=1 \
    PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH
RUN apk add --no-cache libc6-compat \
    && npm install --global --no-fund --no-audit pnpm@${PNPM_VERSION}
WORKDIR /app

# Зависимости отдельным слоем: пересобираются только при смене lockfile.
FROM base AS deps
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN --mount=type=cache,id=pnpm-store,target=/pnpm/store \
    pnpm config set store-dir /pnpm/store \
    && pnpm install --frozen-lockfile

FROM base AS build
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Rewrites /api → бэкенд вычисляются при сборке и попадают в routes-manifest.json,
# поэтому адрес бэкенда — build-аргумент, а не переменная окружения рантайма.
# По умолчанию — сервис backend из docker-compose.yml (порт контейнера 8000).
ARG BACKEND_URL=http://backend:8000
ENV BACKEND_URL=${BACKEND_URL}
RUN pnpm build

FROM node:${NODE_VERSION} AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
# Непривилегированный пользователь node уже есть в официальном образе.
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
