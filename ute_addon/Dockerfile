FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

ENV LANG C.UTF-8
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
RUN pip install --no-cache-dir requests playwright==1.49.0

WORKDIR /app

# Copy scraper package
COPY ute_pkg /app/ute_pkg

# Copy add-on main script and runner
COPY main.py /app/main.py
COPY run.sh /app/run.sh

RUN chmod a+x /app/run.sh

CMD [ "/app/run.sh" ]
