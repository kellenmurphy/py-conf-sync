FROM dhi.io/python:3.13-debian13-dev
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download Playwright's Chromium browser binary into a world-readable path.
# --with-deps is intentionally omitted: it pulls in Xvfb and X11 server packages
# that fail to configure in this apt environment. Chromium in headless mode does
# not need a display server; the required shared libraries are installed below.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers
RUN playwright install chromium

# Install Chromium's runtime library dependencies and bundle mermaid.min.js
# at build time so diagram rendering works fully offline at runtime.
# Node.js is only needed here to npm-install mermaid and extract its dist file.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libasound2t64 libatk-bridge2.0-0t64 libatk1.0-0t64 libatspi2.0-0t64 \
        libcairo2 libcups2t64 libdbus-1-3 libdrm2 libgbm1 libglib2.0-0t64 \
        libnspr4 libnss3 libpango-1.0-0 \
        libx11-6 libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
        libxi6 libxkbcommon0 libxrandr2 libxrender1 \
        fonts-liberation fonts-noto-color-emoji \
        nodejs npm \
    && npm install --prefix /tmp/mermaid mermaid \
    && cp /tmp/mermaid/node_modules/mermaid/dist/mermaid.min.js /app/mermaid.min.js \
    && rm -rf /tmp/mermaid /var/lib/apt/lists/* \
    && chmod -R a+rX /opt/playwright-browsers

COPY py_conf_sync.py .
ENTRYPOINT ["python", "/app/py_conf_sync.py"]
