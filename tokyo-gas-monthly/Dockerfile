FROM ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.23

RUN apk add --no-cache \
    chromium \
    chromium-chromedriver \
    xvfb \
    nss \
    freetype \
    harfbuzz \
    ttf-freefont

RUN pip install --no-cache-dir selenium

WORKDIR /app

COPY tg_scrape.py /app/tg_scrape.py
COPY run.sh /app/run.sh

RUN chmod +x /app/run.sh

CMD ["/app/run.sh"]
