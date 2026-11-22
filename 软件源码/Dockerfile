FROM python:3.12-slim
WORKDIR /app
COPY *.py seed.json ./
COPY public ./public
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python","server.py","--data","/data","--host","0.0.0.0","--port","8787"]
