FROM python:3.12-slim AS app
WORKDIR /app
COPY requirements.txt requirements-test.txt ./
RUN pip install --no-cache-dir -r requirements-test.txt
COPY . .

# Integration tests use an ephemeral, build-local PostgreSQL instance.
# Never point TEST_DATABASE_URL at production: these tests create/drop schemas.
FROM app AS verification
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql \
    && PG_VERSION=$(pg_lsclusters -h | awk 'NR==1{print $1}') \
    && sed -i '1i host all all 127.0.0.1/32 trust' "/etc/postgresql/$PG_VERSION/main/pg_hba.conf" \
    && pg_ctlcluster "$PG_VERSION" main start \
    && su postgres -c 'createuser --superuser root' \
    && (TEST_DATABASE_URL=postgresql://root@127.0.0.1/postgres python -m unittest discover -s tests -v > /tmp/trevixo-tests.log 2>&1; rc=$?; if [ "$rc" -ne 0 ]; then echo '=== Test failure summary ==='; grep -E '^((FAIL|ERROR):|Ran [0-9]+ tests|FAILED|Traceback|AssertionError)' /tmp/trevixo-tests.log || true; tail -n 35 /tmp/trevixo-tests.log; else tail -n 5 /tmp/trevixo-tests.log; fi; exit "$rc") \
    && touch /tmp/trevixo-ci-passed

# PostgreSQL server and test fixtures do not enter the production image.
FROM app AS production
COPY --from=verification /tmp/trevixo-ci-passed /tmp/trevixo-ci-passed
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["sh","-c","uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
