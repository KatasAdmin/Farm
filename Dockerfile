FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python -m py_compile main.py && python -m unittest discover -s tests -p test_bot_operations.py -v && (python -m unittest discover -s tests -v > /tmp/trevixo-tests.log 2>&1; result=$?; tail -n 110 /tmp/trevixo-tests.log; exit "$result")
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["sh","-c","uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
