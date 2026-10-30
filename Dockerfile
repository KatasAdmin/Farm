FROM postgres:18-alpine
RUN apk add --no-cache python3 py3-pip su-exec && python3 -m venv /opt/backup-venv \
 && /opt/backup-venv/bin/pip install --no-cache-dir "boto3==1.40.76"
WORKDIR /backup
COPY requirements.txt /backup/requirements.txt
RUN /opt/backup-venv/bin/pip install --no-cache-dir -r requirements.txt
COPY backup.py validate_database.py main.py production.py production_v4.py /backup/
RUN mkdir -p /backup/assets
ENV PYTHONUNBUFFERED=1
CMD ["/opt/backup-venv/bin/python","/backup/backup.py"]
