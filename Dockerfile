FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create data and logs directories
RUN mkdir -p data logs

CMD ["python", "-m", "ddbot.main"]
