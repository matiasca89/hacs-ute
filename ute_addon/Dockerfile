FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

ENV LANG=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Chromium comes from the base image; install its matching Python client and the
# small Supervisor API client used by the add-on.
RUN pip install --no-cache-dir playwright==1.49.0 requests

WORKDIR /app

# Copy scraper package
COPY ute_pkg /app/ute_pkg

# Copy add-on main script and runner
COPY main.py /app/main.py
COPY run.sh /app/run.sh

RUN chmod a+x /app/run.sh

CMD [ "/app/run.sh" ]
