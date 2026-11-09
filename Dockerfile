FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py market.py tools.py mcp_server.py ./

EXPOSE 8000

CMD ["python", "mcp_server.py"]
