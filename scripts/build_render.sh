#!/usr/bin/env bash
pip install -r requirements.txt
python manage.py migrate
nodeenv -p --node=12.14.0
unset NODE_ENV
npm install
npm run build-assets
