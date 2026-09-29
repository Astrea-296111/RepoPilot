FROM python:3.12-slim
WORKDIR /workspace/project
COPY pyproject.toml README.md ./
COPY repopilot ./repopilot
RUN pip install --no-cache-dir .
RUN useradd -u 10001 -m repopilot
USER repopilot
EXPOSE 8000
CMD ["uvicorn", "repopilot.api.server:app", "--host", "0.0.0.0", "--port", "8000"]

