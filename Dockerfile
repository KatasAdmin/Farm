FROM postgres:18-alpine
RUN apk add --no-cache python3 py3-pip && python3 -m venv /opt/backup-venv \
 && /opt/backup-venv/bin/pip install --no-cache-dir "boto3==1.40.76"
WORKDIR /backup
COPY backup.py /backup/backup.py
ENV PYTHONUNBUFFERED=1
CMD ["/opt/backup-venv/bin/python","/backup/backup.py"]
