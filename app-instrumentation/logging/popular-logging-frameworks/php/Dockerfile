FROM php:8.5-cli-alpine@sha256:26c79a16621a4dc56b0fbb2fa94df4110c972b19855e5aed1cf952ecfa466785

WORKDIR /app

# Install Composer
RUN curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer

# Create composer.json for Monolog
RUN echo '{"require": {"monolog/monolog": "^3.5"}}' > composer.json

# Install dependencies
RUN composer install --no-dev --optimize-autoloader

COPY app.php .

CMD ["php", "app.php"] 