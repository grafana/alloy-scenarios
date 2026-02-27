FROM php:8.3-cli-alpine@sha256:8281275c2b7fb10c149a049e832fae6e936890f839561dbe2ca0d69fc322853f

WORKDIR /app

# Install Composer
RUN curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer

# Create composer.json for Monolog
RUN echo '{"require": {"monolog/monolog": "^3.5"}}' > composer.json

# Install dependencies
RUN composer install --no-dev --optimize-autoloader

COPY app.php .

CMD ["php", "app.php"] 