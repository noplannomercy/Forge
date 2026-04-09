FROM python:3.11-slim

# LibreOffice Impress (PPTX→PDF 변환용) + curl (healthcheck용)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libreoffice-impress \
        libreoffice-core \
        curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# non-root 사용자 생성
RUN groupadd --system forge && useradd --system --gid forge --create-home forge

WORKDIR /app

# 의존성 설치 (레이어 캐시 최적화)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드
COPY --chown=forge:forge . .

USER forge

EXPOSE 8003

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8003/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8003"]
