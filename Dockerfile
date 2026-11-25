FROM python:3.13-slim
WORKDIR /app
COPY investor_backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
ENV PYTHONPATH=/app/investor_backend
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 45 'app:create_app()'"]
