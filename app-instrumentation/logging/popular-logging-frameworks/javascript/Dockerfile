FROM node:24-alpine@sha256:d1b3b4da11eefd5941e7f0b9cf17783fc99d9c6fc34884a665f40a06dbdfc94f

WORKDIR /app

# Create package.json and install pino with pino-pretty for better output formatting
RUN echo '{"name": "logging-example", "version": "1.0.0", "dependencies": {"pino": "^8.17.2", "pino-pretty": "^10.3.1"}}' > package.json
RUN npm install

COPY app.js .

RUN chmod +x app.js

CMD ["node", "app.js"] 