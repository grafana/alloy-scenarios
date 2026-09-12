FROM node:24-alpine@sha256:50c8e8ca1d27439048670df5883f32d57cf81cff6233222c893fd0d9884cbd81

WORKDIR /app

# Create package.json and install pino with pino-pretty for better output formatting
RUN echo '{"name": "logging-example", "version": "1.0.0", "dependencies": {"pino": "^8.17.2", "pino-pretty": "^10.3.1"}}' > package.json
RUN npm install

COPY app.js .

RUN chmod +x app.js

CMD ["node", "app.js"] 