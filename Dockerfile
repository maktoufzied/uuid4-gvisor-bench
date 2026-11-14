# Probe image for LiveKit Cloud: `lk agent create .` builds this file.
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
RUN useradd -m -u 10001 appuser
WORKDIR /app
COPY bench.py pickup.py proof.py agent.py /app/
USER appuser
CMD ["python", "agent.py", "start"]
