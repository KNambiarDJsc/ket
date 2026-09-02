# Phase 14 (Environment Engineering): containerizes the Phase 11 example
# DB app so VeriForge's own tests can exercise a real, isolated,
# throwaway environment instead of a process started directly on the
# host. app.py is stdlib-only (http.server + sqlite3) -- no extra
# dependencies to install, just the base interpreter.
FROM python:3.11-slim
WORKDIR /app
COPY app.py .
EXPOSE 8001
CMD ["python", "app.py"]
