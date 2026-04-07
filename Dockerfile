FROM python:3.12-slim

WORKDIR /mammon

# Install dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the full engine
COPY . .

EXPOSE 5000

# Defaults — override via docker-compose env_file or -e flags
ENV MAMMON_API_TOKEN=dev-token
ENV MAMMON_DASHBOARD_PORT=5000

CMD ["python", "dashboard.py"]
