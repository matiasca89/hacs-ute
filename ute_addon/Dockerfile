FROM python:3.10-slim-bookworm

ENV LANG=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install only Chromium and the system libraries it requires.  The official
# Playwright image bundles Chromium, Firefox and WebKit; this add-on uses only
# Chromium.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN pip install --no-cache-dir playwright==1.49.0 requests \
    && playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/* /root/.cache

WORKDIR /app

# Copy scraper package
COPY ute_pkg /app/ute_pkg

# Copy add-on main script and runner
COPY main.py /app/main.py
COPY run.sh /app/run.sh

RUN chmod a+x /app/run.sh

CMD [ "/app/run.sh" ]
