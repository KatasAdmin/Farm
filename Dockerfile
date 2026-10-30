FROM postgres:18-alpine
RUN apk add --no-cache python3 py3-pip && python3 -m venv /opt/reset-venv \
 && /opt/reset-venv/bin/pip install --no-cache-dir "boto3==1.40.76" "psycopg[binary]==3.2.12"
WORKDIR /reset
COPY reset_once.py /reset/reset_once.py
ENV PYTHONUNBUFFERED=1
CMD ["/opt/reset-venv/bin/python","/reset/reset_once.py"]
