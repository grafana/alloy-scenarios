FROM node:22-alpine@sha256:e4bf2a82ad0a4037d28035ae71529873c069b13eb0455466ae0bc13363826e34

WORKDIR /app

# Create package.json and install pino with pino-pretty for better output formatting
RUN echo '{"name": "logging-example", "version": "1.0.0", "dependencies": {"pino": "^8.17.2", "pino-pretty": "^10.3.1"}}' > package.json
RUN npm install

COPY app.js .

RUN chmod +x app.js

CMD ["node", "app.js"] 