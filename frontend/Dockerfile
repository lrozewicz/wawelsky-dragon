# Obraz web: build SPA (vite) + runtime Bun z serve.ts (statyka + reverse proxy).
# Kontrakt: work/wp/E0-3/CONTRACT.md C9; metryka rozmiaru: C2 (≤ 120 MB).
FROM oven/bun:1.4.2-alpine AS deps
WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

FROM deps AS build
COPY . .
RUN bun run build

# Kontrakt wspólnego CI (etap `test`): typy, lint, testy jednostkowe i test serwera — jak w `.claude/verify-fast.sh`
# (bez e2e Playwright, które potrzebują przeglądarki i stosu). Vitest z jsdom wymaga Node (pod samym Bunem
# `addEventListener` jsdom pada), a `bun run` wybiera Node wg shebangu, gdy jest w PATH — stąd obraz node + binarka bun.
# Błąd kroku = czerwony PR.
FROM node:24.16.0-alpine AS test
COPY --from=oven/bun:1.4.2-alpine /usr/local/bin/bun /usr/local/bin/bun
WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile
COPY . .
RUN bun run typecheck \
    && bun run lint \
    && VITEST_MAX_WORKERS=4 bun run test \
    && bun test ./serve.test.ts \
    && bun run build \
    && bun run bundle-budget

FROM oven/bun:1.4.2-alpine AS runtime
WORKDIR /app
COPY --from=build /app/dist ./dist
COPY serve.ts ./
ENV TZ=Europe/Warsaw PORT=8080 NODE_ENV=production
USER bun
EXPOSE 8080
CMD ["bun", "serve.ts"]
