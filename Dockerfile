# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables to prevent Python from writing pyc files to disc
ENV PYTHONDONTWRITEBYTECODE 1
# Ensure Python output is sent straight to terminal without being buffered
ENV PYTHONUNBUFFERED 1

# Set the working directory in the container
WORKDIR /app

# Install dependencies
# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
# This copies app.py and any other files/folders at the root level
COPY . /app

# Make port 5000 available (this is the default Flask port inside the container)
EXPOSE 5002

# Set environment variables for Flask
# --- Corrected FLASK_APP ---
ENV FLASK_APP=app.py
# Optional: Set Flask environment
ENV FLASK_ENV=development
# Change to production later

# Command to run the application using Flask's built-in server
# Use --host=0.0.0.0 to make it accessible outside the container
# Use --port=5000 to match the EXPOSE directive
CMD ["flask", "run", "--host=0.0.0.0", "--port=5002"]

# --- Alternative CMD using Gunicorn (Recommended for Production) ---
# Ensure gunicorn is in requirements.txt
# CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"] # Point to the app object inside app.py
