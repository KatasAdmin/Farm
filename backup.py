"""One-shot, read-only PostgreSQL backup to Railway S3 storage.
Restores only into a disposable Unix-socket-only database for validation.\nNever restores or modifies the live DB. Exits nonzero if verification fails.
"""
import datetime as dt
import hashlib
import logging
import os
import pathlib
import subprocess
import tempfile
from validate_database import validate_archive

import boto3
from botocore.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("farm_backup")

def sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def check_archive(path):
    result=subprocess.run(["pg_restore","--list",str(path)],capture_output=True,text=True,check=True,timeout=90)
    if "TABLE DATA" not in result.stdout:
        raise RuntimeError("Archive does not contain any table data")
    return result.stdout.count("TABLE DATA")

def main():
    uri=os.environ["DATABASE_URL"]
    endpoint=os.environ["BACKUP_ENDPOINT"]
    bucket=os.environ["BACKUP_BUCKET"]
    region=os.environ.get("BACKUP_REGION","auto")
    client=boto3.client("s3",endpoint_url=endpoint,region_name=region,
        aws_access_key_id=os.environ["BACKUP_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["BACKUP_SECRET_ACCESS_KEY"],
        config=Config(s3={"addressing_style":"virtual"},retries={"max_attempts":3,"mode":"standard"}))
    now=dt.datetime.now(dt.timezone.utc)
    key="postgres/daily/"+now.strftime("%Y/%m/%d/farm-%Y%m%dT%H%M%SZ.dump")
    env=dict(os.environ)
    with tempfile.TemporaryDirectory(prefix="farm-db-backup-") as directory:
        path=pathlib.Path(directory)/"database.dump"
        log.info("Starting read-only pg_dump to local temporary file")
        subprocess.run(["pg_dump","--no-password","--format=custom","--compress=6",
            "--file="+str(path),"--dbname="+uri],env=env,check=True,timeout=600)
        tables=check_archive(path)
        size=path.stat().st_size
        digest=sha256(path)
        if size<1024:
            raise RuntimeError("Backup unusually small; refusing upload")
        log.info("pg_restore archive structure verified: %s table data records, %s bytes",tables,size)
        client.upload_file(str(path),bucket,key,ExtraArgs={"Metadata":{"sha256":digest,"format":"pg-dump-custom-v1"}})
        obj=client.head_object(Bucket=bucket,Key=key)
        if obj["ContentLength"]!=size or obj.get("Metadata",{}).get("sha256")!=digest:
            raise RuntimeError("Uploaded object metadata/size verification failed")
        downloaded=pathlib.Path(directory)/"downloaded.dump"
        client.download_file(bucket,key,str(downloaded))
        if sha256(downloaded)!=digest:
            raise RuntimeError("Downloaded backup SHA256 mismatch")
        check_archive(downloaded)
        validate_archive(downloaded)
        log.info("BACKUP_OK key=%s size=%d sha256=%s",key,size,digest)
    # Keep a 30-day rolling history only after verified new backup.
    cutoff=now-dt.timedelta(days=30)
    pager=client.get_paginator("list_objects_v2")
    for page in pager.paginate(Bucket=bucket,Prefix="postgres/daily/"):
        for obj in page.get("Contents",[]):
            if obj["LastModified"]<cutoff and obj["Key"]!=key:
                client.delete_object(Bucket=bucket,Key=obj["Key"])
                log.info("Purged expired backup object %s",obj["Key"])

if __name__=="__main__":
    main()

# On-demand prelaunch snapshot build trigger.
