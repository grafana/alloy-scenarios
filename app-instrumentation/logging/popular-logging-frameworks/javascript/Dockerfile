FROM node:24-alpine@sha256:7fddd9ddeae8196abf4a3ef2de34e11f7b1a722119f91f28ddf1e99dcafdf114

WORKDIR /app

# Create package.json and install pino with pino-pretty for better output formatting
RUN echo '{"name": "logging-example", "version": "1.0.0", "dependencies": {"pino": "^8.17.2", "pino-pretty": "^10.3.1"}}' > package.json
RUN npm install

COPY app.js .

RUN chmod +x app.js

CMD ["node", "app.js"] 