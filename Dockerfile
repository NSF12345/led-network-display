FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY web/ ./web/

# Set by the CI build (see .github/workflows/docker-publish.yml) to the
# commit this image was actually built from - not bumped by hand. Falls
# back to "dev" for a local `docker build` with no --build-arg given.
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

EXPOSE 8080

CMD ["python", "-m", "app.main"]
