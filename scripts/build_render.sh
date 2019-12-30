#!/usr/bin/env bash
pip install -r requirements.txt
python manage.py migrate
unset NODE_ENV
npm install
npm run build-assets
python manage.py collectstatic --no-input
