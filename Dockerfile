FROM python:3.9

USER root

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /app/cache && chmod 777 /app/cache
ENV TRANSFORMERS_CACHE=/app/cache
ENV HF_HOME=/app/cache

EXPOSE 7860

CMD ["gunicorn", "-b", "0.0.0.0:7860", "app:app"]