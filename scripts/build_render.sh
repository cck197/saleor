#!/usr/bin/env bash
cd ..
pip install -r requirements.txt
python manage.py migrate
#nodeenv -p --node=12.14.0
#npm install
#npm run build-assets
