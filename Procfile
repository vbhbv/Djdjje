web: apt update && apt install -y ffmpeg && gunicorn --workers 4 --timeout 120 --bind 0.0.0.0:$PORT main:app
