FROM node:24-alpine
WORKDIR /opt/game
COPY package*.json ./
RUN npm ci --omit=dev --ignore-scripts && mkdir -p /data/receipts /data/runs && chown -R node:node /data
COPY server.mjs ./
COPY public ./public
USER node
EXPOSE 8088
CMD ["node", "server.mjs"]
