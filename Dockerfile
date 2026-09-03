# The frontend. Its counterpart is backend/Dockerfile, which ships the API and
# the ingest batch as one image; this one is separate because it is a different
# runtime, not a different command.
#
# Built in two stages so the runtime carries the traced server bundle and
# nothing else: no toolchain, no dev dependencies, no source.

FROM node:22-slim AS build

WORKDIR /app

# dependencies first, so a source change does not reinstall them
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# The build reads /stats to render the chrome. It must not reach for a real API
# at build time — every page is dynamic and rendered per request — so nothing
# here points at one.
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build


FROM node:22-slim AS runtime

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# not root: the container has no reason to be able to write to its own image
RUN groupadd --system --gid 1001 readbase \
 && useradd --system --uid 1001 --gid readbase readbase

COPY --from=build --chown=readbase:readbase /app/.next/standalone ./
COPY --from=build --chown=readbase:readbase /app/.next/static ./.next/static
COPY --from=build --chown=readbase:readbase /app/public ./public

USER readbase
EXPOSE 3000

# READBASE_API_URL and READBASE_API_KEY are read at request time, not baked in,
# so one image serves every environment.
CMD ["node", "server.js"]
