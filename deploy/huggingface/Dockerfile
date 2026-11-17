# MURAFLEX AUTOMATION - Hugging Face Space (free CPU: 2 cores, 16 GB RAM -> scanned PDFs are read by OCR too).
# The Space holds only this file and README.md; the app itself is pulled from GitHub at every build.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# changes whenever GitHub main changes -> "Factory rebuild" always pulls the latest version
ADD https://api.github.com/repos/254pavan789/muraflex-automation/commits/main /tmp/latest-commit.json
RUN git clone --depth 1 https://github.com/254pavan789/muraflex-automation /app

WORKDIR /app
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "from rapidocr import RapidOCR; RapidOCR()"

RUN useradd -m -u 1000 user && chown -R user /app
USER user

ENV GLASS_PUBLIC=1 \
    GLASS_ALLOW=* \
    GLASS_OCR=on \
    GLASS_DATA_DIR=/tmp/glass_data \
    PYTHONUNBUFFERED=1
EXPOSE 7860
CMD ["python", "app.py", "--no-browser", "--port", "7860"]
