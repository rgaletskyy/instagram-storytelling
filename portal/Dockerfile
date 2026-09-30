# The marketing portal, for Cloud Run. See portal/README.md.
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0
# The standalone server serves .next/static and public only if they sit beside it.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
USER node
# Cloud Run sets PORT, which server.js reads.
CMD ["node", "server.js"]
