FROM php:8.5-cli-alpine@sha256:6ca76906d789edfac74e5f109c800b71e571bd313277133eaddc079733ee0b65

WORKDIR /app

# Install Composer
RUN curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer

# Create composer.json for Monolog
RUN echo '{"require": {"monolog/monolog": "^3.5"}}' > composer.json

# Install dependencies
RUN composer install --no-dev --optimize-autoloader

COPY app.php .

CMD ["php", "app.php"] 