# CIRA intake interface.
#
# One image, one process: FastAPI serves both the page and the agent API, so
# there is no separate frontend to build or host.
#
#   docker build -t cira .
#   docker run -p 8000:8000 -e OPENAI_API_KEY=sk-... -v "$PWD/records:/records" cira
#
# The volume is not optional in any real use. Records are written to the
# working directory, and a container's filesystem is discarded when it stops.

FROM python:3.12-slim

# Unbuffered output so a host's log viewer shows a crash as it happens rather
# than whenever the buffer happens to flush.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies first, as their own layer: application edits are frequent and
# should not reinstall the whole stack.
COPY cira/requirements.txt ./cira/requirements.txt
RUN pip install --no-cache-dir -r cira/requirements.txt

COPY cira ./cira

# Records land in the working directory, so the working directory is the
# mount point rather than the source tree.
WORKDIR /records

# A container reached from outside must bind every interface; the default is
# loopback precisely so that running it by hand does not expose it by accident.
#
# CIRA_RECORD_DIR points at the writable location for records. Override it to
# the host's persistent disk - /data on Hugging Face Spaces - or records live
# only as long as the container does.
ENV CIRA_HOST=0.0.0.0 \
    CIRA_PORT=8000 \
    CIRA_RECORD_DIR=/records
EXPOSE 8000

# Nothing privileged here, and the records directory must be writable by the
# user that writes them. uid 1000 is what Hugging Face Spaces expects, and is
# unremarkable everywhere else.
RUN useradd --create-home --uid 1000 cira && chown cira /records
USER cira

CMD ["python", "/app/cira/main.py"]
