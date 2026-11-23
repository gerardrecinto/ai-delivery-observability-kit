FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[server]" \
    && useradd --system --uid 10001 app
USER 10001
ENV HOST=0.0.0.0 PORT=8000
EXPOSE 8000
CMD ["python", "-m", "aidelivery.mock_server"]
