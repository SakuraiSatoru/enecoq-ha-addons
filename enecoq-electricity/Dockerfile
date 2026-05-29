FROM ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.23

WORKDIR /app

COPY enecoq_scrape.py /app/enecoq_scrape.py
COPY run.sh /app/run.sh

RUN chmod +x /app/run.sh

CMD ["/app/run.sh"]
