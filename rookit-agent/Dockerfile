FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY rookit ./rookit
COPY data ./data
ENV ROOKIT_MODE=replay
EXPOSE 8000
CMD ["uvicorn", "rookit.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
