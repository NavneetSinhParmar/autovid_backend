FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y ffmpeg fontconfig && \
    rm -rf /var/lib/apt/lists/*

COPY app/Fonts /usr/share/fonts/truetype/custom
RUN fc-cache -f -v


WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /app/media

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
