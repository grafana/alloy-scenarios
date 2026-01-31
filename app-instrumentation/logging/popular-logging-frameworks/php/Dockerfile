FROM php:8.5-cli-alpine@sha256:166a9ddf511d6782b44a05a086a8de5271483441c9f8c8f5d526ae0d5466c32d

WORKDIR /app

# Install Composer
RUN curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer

# Create composer.json for Monolog
RUN echo '{"require": {"monolog/monolog": "^3.5"}}' > composer.json

# Install dependencies
RUN composer install --no-dev --optimize-autoloader

COPY app.php .

CMD ["php", "app.php"] 