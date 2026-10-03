FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/project
COPY pyproject.toml README.md ./
COPY repopilot ./repopilot
RUN pip install --no-cache-dir '.[full]' 'pytest>=8,<10'
RUN useradd -u 10001 -m repopilot
USER repopilot
EXPOSE 8000
CMD ["uvicorn", "repopilot.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
