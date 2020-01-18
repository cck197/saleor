#!/usr/bin/env bash
pip install -r requirements.txt
pip install -r requirements_nodeps.txt --no-deps
python manage.py migrate
unset NODE_ENV
npm install
npm run build-assets
npm run build-emails
python manage.py collectstatic --no-input
