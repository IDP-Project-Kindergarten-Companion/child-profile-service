from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# Configuration for the database interaction service (mock or real)
# We use the service name defined in docker-compose.yml as the hostname within the Docker network
DB_INTERACT_SERVICE_HOST = os.environ.get('DB_INTERACT_SERVICE_HOST', 'db-interact')
# Assuming the target service (mock or real) is listening on port 5002 internally
DB_INTERACT_SERVICE_PORT = os.environ.get('DB_INTERACT_SERVICE_PORT', '5002')
DB_INTERACT_ADD_CHILD_ROUTE = os.environ.get('DB_INTERACT_ADD_CHILD_ROUTE', '/add_child')

@app.route('/children', methods=['POST'])
def add_child_profile():
    """
    Receives child profile data, validates it, and sends it to the configured
    database interaction service (mock or real).
    Expected JSON body:
    {
        "firstName": "string",
        "lastName": "string",
        "allergies": "string",
        "dateOfBirth": "YYYY-MM-DD"
    }
    """
    data = request.get_json()

    # Basic validation of input data
    if not data:
        return jsonify({"error": "Invalid JSON data"}), 400

    required_fields = ["firstName", "lastName", "allergies", "dateOfBirth"]
    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"Missing field: {field}"}), 400

    # You might want more robust validation for date format, etc.

    # Prepare data to send to the database interaction service
    # Ensure the data format matches what the target service expects
    # Note: Using snake_case for keys assuming the db-interact service expects this
    db_payload = {
        "first_name": data.get("firstName"),
        "last_name": data.get("lastName"),
        "allergies": data.get("allergies"),
        "date_of_birth": data.get("dateOfBirth")
    }

    # Construct the URL for the target service using the environment variables
    db_interact_url = f"http://{DB_INTERACT_SERVICE_HOST}:{DB_INTERACT_SERVICE_PORT}{DB_INTERACT_ADD_CHILD_ROUTE}"

    try:
        # Make the POST request to the target service
        app.logger.info(f"Attempting to send data to db-interact service at {db_interact_url}")
        response = requests.post(db_interact_url, json=db_payload)
        app.logger.info(f"Received response from db-interact service: Status Code {response.status_code}")

        # Check the response from the target service
        if response.status_code in [200, 201]: # Assuming 200 OK or 201 Created indicates success
            # Return success response from child-profile-service
            try:
                db_response_json = response.json()
            except requests.exceptions.JSONDecodeError:
                db_response_json = {"message": "Could not decode JSON response from db-interact"}

            return jsonify({"message": "Child profile added successfully", "db_response": db_response_json}), response.status_code
        else:
            # Return error response from the target service to the client
            return jsonify({"error": "Failed to add child profile via database interaction service", "db_status_code": response.status_code, "db_error": response.text}), response.status_code

    except requests.exceptions.ConnectionError:
        app.logger.error(f"Connection Error: Could not connect to database interaction service at {db_interact_url}")
        return jsonify({"error": f"Could not connect to database interaction service at {db_interact_url}. Is the service running and accessible?"}), 500
    except Exception as e:
        app.logger.error(f"An unexpected error occurred: {str(e)}")
        return jsonify({"error": f"An unexpected error occurred in child-profile-service: {str(e)}"}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Simple health check endpoint."""
    return jsonify({"status": "child profile service healthy"}), 200


if __name__ == '__main__':
    # Run the Flask app
    # Listen on all interfaces on port 5000
    # In production, use a production-ready WSGI server like Gunicorn or uWSGI
    app.run(host='0.0.0.0', port=5000, debug=True) # debug=True for development logging
