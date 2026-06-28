FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    fonts-liberation \
    libnss3 \
    libatk-bridge2.0-0 \
    libgbm1 \
    libasound2 \
    libxss1 \
    libxtst6 \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome Stable (sends real "Google Chrome" brand in sec-ch-ua,
# which CF's JSD fingerprint requires to pass without serving a challenge).
RUN wget -q -O /tmp/google-chrome.deb \
    https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get update \
    && apt-get install -y --no-install-recommends /tmp/google-chrome.deb \
    && rm /tmp/google-chrome.deb \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir fastapi==0.115.12 uvicorn==0.34.0 nodriver==0.44 httpx

WORKDIR /app
COPY app.py .

ENV DISPLAY=:99
ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["bash", "-c", "rm -f /tmp/.X99-lock && Xvfb :99 -screen 0 1280x720x24 -nolisten tcp & sleep 1 && uvicorn app:app --host 0.0.0.0 --port 8080"]
