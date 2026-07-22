# Use an official Python runtime
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Hugging Face requires applications to listen on port 7860
EXPOSE 7860

# Set up a non-root user (Required by Hugging Face Docker Spaces)
RUN useradd -m -u 1000 user
USER user

# Command to run the application
CMD ["python", "app.py"]
