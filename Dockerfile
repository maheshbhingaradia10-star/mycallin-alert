FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && python -m playwright install --with-deps chromium
RUN useradd --create-home runner && mkdir -p /app/private_output && chown runner:runner /app/private_output
COPY mycallin_alert.py render_runner.py ./
USER runner
CMD ["python", "render_runner.py"]
