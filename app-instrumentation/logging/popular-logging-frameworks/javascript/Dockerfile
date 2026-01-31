FROM node:24-alpine@sha256:cd6fb7efa6490f039f3471a189214d5f548c11df1ff9e5b181aa49e22c14383e

WORKDIR /app

# Create package.json and install pino with pino-pretty for better output formatting
RUN echo '{"name": "logging-example", "version": "1.0.0", "dependencies": {"pino": "^8.17.2", "pino-pretty": "^10.3.1"}}' > package.json
RUN npm install

COPY app.js .

RUN chmod +x app.js

CMD ["node", "app.js"] 