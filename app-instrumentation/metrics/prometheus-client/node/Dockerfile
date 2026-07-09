FROM node:24-alpine@sha256:a0b9bf06e4e6193cf7a0f58816cc935ff8c2a908f81e6f1a95432d679c54fbfd
WORKDIR /app
COPY package.json ./
RUN npm install
COPY app.js ./
CMD ["node", "app.js"]
