FROM php:8.5-cli-alpine@sha256:8d7090ce03736b6ecfd739d87a46ab59b5d1d0d837f1ac7c5d2702f1d312f5a0

WORKDIR /app

# Install Composer
RUN curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer

# Create composer.json for Monolog
RUN echo '{"require": {"monolog/monolog": "^3.5"}}' > composer.json

# Install dependencies
RUN composer install --no-dev --optimize-autoloader

COPY app.php .

CMD ["php", "app.php"] 