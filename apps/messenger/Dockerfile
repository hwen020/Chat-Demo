FROM node:22-alpine AS frontend
WORKDIR /src
COPY apps/messenger/web/package*.json ./
RUN npm ci
COPY apps/messenger/web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY apps/messenger/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home appuser
COPY apps/messenger/api/ .
COPY packages/shared/python/chatflow_shared /app/chatflow_shared
COPY --from=frontend /src/dist /app/web
COPY services/render-start.sh /app/render-start.sh
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--ws-max-size", "32768"]
