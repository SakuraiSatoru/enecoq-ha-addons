FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

RUN pip install --no-cache-dir enecoq-data-fetcher==2.2.1

WORKDIR /app

COPY enecoq_scrape.py /app/enecoq_scrape.py
COPY run.sh /app/run.sh

RUN chmod +x /app/run.sh

CMD ["/app/run.sh"]
