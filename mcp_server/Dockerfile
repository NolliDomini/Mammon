FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

EXPOSE 5001

ENV MAMMON_BASE=/mammon
ENV REDIS_HOST=redis
ENV REDIS_PORT=6379
ENV MCP_PORT=5001

CMD ["python", "server.py"]
