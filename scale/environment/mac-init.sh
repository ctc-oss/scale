#!/usr/bin/env bash

export SCALE_DB_PORT=55432
export SCALE_DB_PASS=scale-postgres

# Launch a database for Scale testing
docker run -d --restart=always -p ${SCALE_DB_PORT}:5432 --name scale-postgis \
    -e POSTGRES_PASSWORD=${SCALE_DB_PASS} mdillon/postgis:9.4-alpine
echo Giving Postgres a moment to start up before initializing...
sleep 10

# Configure database
cat << EOF > database-commands.sql
CREATE USER scale PASSWORD 'scale' SUPERUSER;
CREATE DATABASE scale OWNER=scale;
EOF
docker cp database-commands.sql scale-postgis:/database-commands.sql
rm database-commands.sql
docker exec -it scale-postgis su postgres -c 'psql -f /database-commands.sql'
docker exec -it scale-postgis su postgres -c 'psql scale -c "CREATE EXTENSION postgis;"'

# Install all python dependencies
brew install gdal
brew install libgeoip

cp scale/local_settings_dev.py scale/local_settings.py
cat << EOF >> scale/local_settings.py
POSTGIS_TEMPLATE = 'template_postgis'

# Example settings for using PostgreSQL database with PostGIS.
DATABASES = {
    'default': {
        'ENGINE': 'django.contrib.gis.db.backends.postgis',
        'NAME': 'scale',
        'USER': 'scale',
        'PASSWORD': 'scale',
        'HOST': 'localhost',
        'PORT': '${SCALE_DB_PORT}',
        'TEST': {'NAME': 'test_scale'},
    },
}
EOF

# Initialize virtual environment
virtualenv environment/scale
environment/scale/bin/pip install -r pip/requirements.txt

# Load up database with schema migrations to date and fixtures
environment/scale/bin/python manage.py migrate
environment/scale/bin/python manage.py load_all_data