FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# --proxy-headers/--forwarded-allow-ips: Railway terminates TLS in front of this
# container. Without them uvicorn builds redirects as http:// (which MCP clients
# refuse) and the MCP rate limiter sees the proxy's address as every caller's.
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips="*"
