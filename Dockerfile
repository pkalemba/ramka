ARG BUILD_FROM
FROM ${BUILD_FROM}

# Zależności systemowe: czcionki + biblioteki dla Pillow
RUN apk add --no-cache \
    font-noto \
    font-noto-cjk \
    freetype \
    libjpeg-turbo \
    libpng \
    zlib

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Opcjonalny katalog na własne fonty TTF
RUN mkdir -p /app/fonts

CMD ["/run.sh"]
