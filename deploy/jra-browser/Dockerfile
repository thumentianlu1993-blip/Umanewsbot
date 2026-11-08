FROM node:22-bookworm-slim
ARG UMANEWS_RELEASE_COMMIT=unknown
LABEL org.opencontainers.image.revision="${UMANEWS_RELEASE_COMMIT}"
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev && npx playwright install --with-deps chromium && chmod -R a+rX /ms-playwright
COPY collector.cjs server.cjs ./
USER node
EXPOSE 8080
CMD ["node", "server.cjs"]
