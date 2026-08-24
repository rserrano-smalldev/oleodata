# Imagen de base de datos: TimescaleDB (series temporales) + PostGIS (geografía)
# sobre PostgreSQL 16. No existe una imagen oficial única y estable que combine
# ambas extensiones bajo un tag fijo verificable, así que se construye explícitamente
# a partir de la imagen oficial de TimescaleDB añadiendo el paquete postgis de Debian.
FROM timescale/timescaledb:latest-pg16

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-16-postgis-3 \
        postgresql-16-postgis-3-scripts \
    && rm -rf /var/lib/apt/lists/*
