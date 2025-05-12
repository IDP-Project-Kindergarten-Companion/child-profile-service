# --- child_profile_service/app.py ---
import os
import datetime
import jwt
import requests
import logging
import traceback
from functools import wraps
from flask import Flask, request, jsonify, g
from requests.exceptions import ConnectionError, Timeout, RequestException # Import specific exceptions
from dotenv import load_dotenv

# --- Load Environment Variables ---
load_dotenv() # Load .env file from the current directory

# --- Flask App Initialization ---
app = Flask(__name__)

# --- Configuration ---
# Load configuration directly into Flask app config
app.config['SECRET_KEY'] = os.environ.get('CHILD_PROFILE_SECRET_KEY', 'a_fallback_secret_for_child_profile')
# --- Corrected Default URL for Separate Execution ---
# Default targets localhost and the HOST port exposed by db-interact-service's compose file.
# REMOVED the /data path from the base URL here.
app.config['DB_INTERACT_SERVICE_URL'] = os.environ.get('DB_INTERACT_SERVICE_URL', 'http://localhost:8082')
# --- End Correction ---
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'default_jwt_secret_key_needs_change') # MUST match other services
app.config['JWT_ALGORITHM'] = "HS256" # Must match other services
app.config['LINKING_CODE_EXPIRATION'] = datetime.timedelta(hours=24) # How long a code is valid
app.config['LINKING_CODE_TYPE_CLAIM'] = "linking_code" # Custom claim to identify these tokens

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO)
logging.info("Child Profile Service starting up...")
logging.info(f"DB Interact Service URL configured as: {app.config.get('DB_INTERACT_SERVICE_URL')}") # Log the configured URL

# --- Decorators ---
def token_required(f):
    """
    Decorator for Child Profile Service routes.
    Ensures a valid ACCESS JWT is present, validates it using the shared secret,
    and loads user info ('user_id', 'role') into Flask's 'g' object.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(" ")[1]

        if not token:
            return jsonify({"message": "Token is missing!"}), 401

        try:
            jwt_secret = app.config.get('JWT_SECRET_KEY')
            jwt_algo = app.config.get('JWT_ALGORITHM', 'HS256')

            if not jwt_secret:
                app.logger.critical("JWT_SECRET_KEY is not configured!")
                return jsonify({"message": "Server configuration error"}), 500

            payload = jwt.decode(
                token,
                jwt_secret,
                algorithms=[jwt_algo],
            )

            if payload.get("type") != "access":
                return jsonify({"message": "Invalid token type provided (expected access)"}), 401

            g.current_user_id = payload.get("sub")
            g.current_user_role = payload.get("role")
            g.current_user_token = token # Store token if needed by service calls

            if g.current_user_id is None or g.current_user_role is None:
                 app.logger.warning("Token payload missing 'sub' or 'role'.")
                 return jsonify({"message": "Invalid token payload"}), 401

        except jwt.ExpiredSignatureError:
            return jsonify({"message": "Access token has expired!"}), 401
        except jwt.InvalidTokenError as e:
            app.logger.warning(f"Invalid access token received: {e}")
            return jsonify({"message": "Access token is invalid!"}), 401
        except Exception as e:
            app.logger.error(f"Unexpected error decoding token: {e}", exc_info=True)
            return jsonify({"message": "Error processing token"}), 500

        return f(*args, **kwargs)
    return decorated_function

# --- Utilities ---
def generate_linking_code(child_id: str) -> str | None:
    """Generates a short-lived JWT to act as a linking code."""
    try:
        secret_key = app.config['JWT_SECRET_KEY']
        algorithm = app.config['JWT_ALGORITHM']
        expires_delta = app.config['LINKING_CODE_EXPIRATION']
        code_type = app.config['LINKING_CODE_TYPE_CLAIM']

        payload = {
            "child_id": child_id,
            "type": code_type,
            "exp": datetime.datetime.utcnow() + expires_delta,
            "iat": datetime.datetime.utcnow()
        }
        linking_code = jwt.encode(payload, secret_key, algorithm=algorithm)
        return linking_code
    except Exception as e:
        app.logger.error(f"Failed to generate linking code for child {child_id}: {e}")
        return None

def verify_linking_code(code: str) -> str | None:
    """
    Verifies a linking code JWT.
    Returns the child_id if valid and not expired, otherwise None.
    """
    try:
        secret_key = app.config['JWT_SECRET_KEY']
        algorithm = app.config['JWT_ALGORITHM']
        code_type = app.config['LINKING_CODE_TYPE_CLAIM']

        payload = jwt.decode(
            code,
            secret_key,
            algorithms=[algorithm]
        )

        if payload.get("type") != code_type:
            app.logger.warning("Attempted to use non-linking code JWT for linking.")
            return None

        child_id = payload.get("child_id")
        if not child_id:
             app.logger.error("Linking code payload missing child_id.")
             return None

        return child_id

    except jwt.ExpiredSignatureError:
        app.logger.info("Expired linking code presented.")
        return None
    except jwt.InvalidTokenError as e:
        app.logger.warning(f"Invalid linking code presented: {e}")
        return None
    except Exception as e:
        app.logger.error(f"Unexpected error verifying linking code: {e}")
        return None

# --- Service Layer (Calls to DB Interact) ---
def _get_db_interact_url():
    # Ensure no trailing slash on the base URL from config
    return app.config.get('DB_INTERACT_SERVICE_URL', '').rstrip('/')

def _make_db_request(method, endpoint, token, data=None, params=None):
    """Makes a request to the DB Interact Service."""
    base_url = _get_db_interact_url()
    # Ensure endpoint starts with a slash
    if not endpoint.startswith('/'):
        endpoint = '/' + endpoint
    url = f"{base_url}{endpoint}" # Construct full URL
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}" # Pass the original token

    try:
        app.logger.info(f"Attempting {method} request to DB Interact: {url}") # Log URL being called
        response = requests.request(
            method, url, headers=headers, json=data, params=params, timeout=10
        )
        # Log details before returning
        app.logger.info(f"DB Interact Request: {method} {url} -> Status: {response.status_code}")
        return response
    except requests.exceptions.ConnectionError as e:
        app.logger.error(f"DB Interact Connection Error to {url}: {e}")
        # Raise a specific error type that can be caught in routes
        raise ConnectionError(f"Could not connect to DB Interact service at {url}") from e
    except requests.exceptions.Timeout as e:
        app.logger.error(f"DB Interact Timeout for {url}: {e}")
        raise TimeoutError(f"Request to DB Interact service timed out") from e
    except requests.exceptions.RequestException as e:
        app.logger.error(f"DB Interact Request Error for {url}: {e}")
        raise # Re-raise other request exceptions

# --- Corrected Endpoint Paths in request_* functions ---

def request_create_child(child_data, parent_token):
    """Sends request to create child record in db-interact."""
    endpoint = "/internal/children" # Correct path
    payload = {
        "name": child_data.get("name"),
        "birthday": child_data.get("birthday"),
        "group": child_data.get("group"),
        "allergies": child_data.get("allergies"),
        "notes": child_data.get("notes"),
    }
    response = _make_db_request("POST", endpoint, token=parent_token, data=payload)
    return response

def request_link_supervisor(child_id, supervisor_id, supervisor_token):
    """Sends request to link supervisor in db-interact."""
    endpoint = f"/internal/children/{child_id}/link-supervisor" # Correct path
    payload = {"supervisor_id": supervisor_id}
    response = _make_db_request("PUT", endpoint, token=supervisor_token, data=payload)
    return response

def request_get_child(child_id, user_token):
    """Sends request to get child data from db-interact's /data endpoint."""
    endpoint = f"/data/children/{child_id}" # Correct path with /data prefix
    response = _make_db_request("GET", endpoint, token=user_token)
    return response

def request_get_children_list(user_token):
    """Sends request to get list of children associated with user from db-interact's /data endpoint."""
    endpoint = "/data/children" # Correct path with /data prefix
    response = _make_db_request("GET", endpoint, token=user_token)
    return response

def request_update_child(child_id, update_data, user_token):
    """Sends request to update child details in db-interact."""
    endpoint = f"/internal/children/{child_id}" # Correct path with /internal prefix
    response = _make_db_request("PUT", endpoint, token=user_token, data=update_data)
    return response

# --- API Routes ---

@app.route('/health', methods=['GET'])
def health_check():
    """Simple health check endpoint."""
    return jsonify({"status": "Child Profile Service Healthy"}), 200

# Use the '/profiles' prefix for consistency with API documentation
@app.route('/profiles/children', methods=['POST'])
@token_required
def add_child():
    """
    Endpoint for a parent to add a new child profile.
    Generates and returns a linking code.
    """
    user_id = g.current_user_id
    user_role = g.current_user_role
    user_token = g.current_user_token # Get token from decorator context

    if user_role != 'parent':
        return jsonify({"message": "Forbidden: Only parents can add children"}), 403

    data = request.get_json()
    required_fields = ["name", "birthday"]
    if not data or any(field not in data for field in required_fields):
        return jsonify({"message": f"Missing required fields: {', '.join(required_fields)}"}), 400

    child_data = {
        "name": data.get("name"),
        "birthday": data.get("birthday"),
        "group": data.get("group"),
        "allergies": data.get("allergies"),
        "notes": data.get("notes"),
    }

    try:
        response = request_create_child(child_data, user_token) # Pass parent's token

        if response.status_code == 201:
            db_response_data = response.json()
            new_child_id = db_response_data.get("child_id")
            if not new_child_id:
                 app.logger.error("DB Interact service created child but did not return child_id.")
                 return jsonify({"message": "Child profile created, but failed to get ID."}), 500

            linking_code = generate_linking_code(new_child_id)
            if not linking_code:
                 app.logger.error(f"Failed to generate linking code for child {new_child_id}.")
                 return jsonify({"message": "Child profile created, but linking code generation failed."}), 500

            return jsonify({
                "message": "Child profile added successfully",
                "child_id": new_child_id,
                "linking_code": linking_code
            }), 201
        else:
             error_msg = "Failed to create child profile via database service."
             try: error_details = response.json().get('message', response.text); error_msg += f" Reason: {error_details}"
             except: error_msg += f" Status: {response.status_code}"
             return jsonify({"message": error_msg}), response.status_code

    except (ConnectionError, TimeoutError, RequestException) as e:
        app.logger.error(f"Error communicating with db-interact service: {e}")
        return jsonify({"message": "Error communicating with database service"}), 503 # Service Unavailable
    except Exception as e:
        app.logger.error(f"Unexpected error in add_child: {e}\n{traceback.format_exc()}")
        return jsonify({"message": "An internal server error occurred"}), 500


@app.route('/profiles/children/link-supervisor', methods=['POST'])
@token_required
def link_supervisor():
    """Endpoint for a supervisor/teacher to link to a child using a code."""
    supervisor_id = g.current_user_id # This is the supervisor's ID
    user_role = g.current_user_role
    supervisor_token = g.current_user_token # Get token from decorator context

    if user_role != 'teacher':
        return jsonify({"message": "Forbidden: Only supervisors can link using a code"}), 403

    data = request.get_json()
    linking_code = data.get('linking_code') if data else None

    if not linking_code:
        return jsonify({"message": "Missing 'linking_code' in request body"}), 400

    child_id = verify_linking_code(linking_code)
    if not child_id:
        return jsonify({"message": "Invalid or expired linking code"}), 400

    try:
        # Call db-interact service to add supervisor_id to child's list
        response = request_link_supervisor(child_id, supervisor_id, supervisor_token)

        if response.status_code == 200:
            return jsonify({"message": "Supervisor linked successfully", "child_id": child_id}), 200
        else:
             error_msg = "Failed to link supervisor via database service."
             try: error_details = response.json().get('message', response.text); error_msg += f" Reason: {error_details}"
             except: error_msg += f" Status: {response.status_code}"
             # Provide more context if child not found
             if response.status_code == 404: error_msg = "Failed to link supervisor: Child not found."
             return jsonify({"message": error_msg}), response.status_code

    except (ConnectionError, TimeoutError, RequestException) as e:
        app.logger.error(f"Error communicating with db-interact service: {e}")
        return jsonify({"message": "Error communicating with database service"}), 503
    except Exception as e:
        app.logger.error(f"Unexpected error in link_supervisor: {e}\n{traceback.format_exc()}")
        return jsonify({"message": "An internal server error occurred"}), 500


@app.route('/profiles/children/<child_id>', methods=['GET'])
@token_required
def get_child(child_id):
    """Gets profile details for a specific child."""
    user_token = g.current_user_token # Get token from decorator context

    try:
        # Request data from db-interact's /data endpoint which includes authz
        response = request_get_child(child_id, user_token)

        try: response_data = response.json()
        except requests.exceptions.JSONDecodeError: response_data = {"message": response.text}

        # Forward status code and data/message from db-interact
        return jsonify(response_data), response.status_code

    except (ConnectionError, TimeoutError, RequestException) as e:
        app.logger.error(f"Error communicating with db-interact service: {e}")
        return jsonify({"message": "Error communicating with database service"}), 503
    except Exception as e:
        app.logger.error(f"Unexpected error in get_child: {e}\n{traceback.format_exc()}")
        return jsonify({"message": "An internal server error occurred"}), 500


@app.route('/profiles/children', methods=['GET'])
@token_required
def get_children_list():
    """Gets a list of children associated with the requesting user."""
    user_token = g.current_user_token # Get token from decorator context

    try:
        # db-interact filters based on the token provided
        response = request_get_children_list(user_token)

        try: response_data = response.json()
        except requests.exceptions.JSONDecodeError: response_data = {"message": response.text}

        # Forward status code and data/message from db-interact
        return jsonify(response_data), response.status_code

    except (ConnectionError, TimeoutError, RequestException) as e:
        app.logger.error(f"Error communicating with db-interact service: {e}")
        return jsonify({"message": "Error communicating with database service"}), 503
    except Exception as e:
        app.logger.error(f"Unexpected error in get_children_list: {e}\n{traceback.format_exc()}")
        return jsonify({"message": "An internal server error occurred"}), 500


@app.route('/profiles/children/<child_id>', methods=['PUT'])
@token_required
def update_child(child_id):
    """Updates editable details for a specific child."""
    user_token = g.current_user_token
    user_id = g.current_user_id

    data = request.get_json()
    if not data:
        return jsonify({"message": "Missing request body"}), 400

    # --- Authorization Check ---
    # Verify the user is allowed to update this child BEFORE making the update call.
    # We call the GET endpoint on db-interact which performs the check.
    try:
        authz_response = request_get_child(child_id, user_token)
        if not authz_response.ok: # Checks for 2xx status codes
            # Forward the error (403 Forbidden, 404 Not Found, etc.)
            try: authz_data = authz_response.json()
            except: authz_data = {"message": authz_response.text}
            app.logger.warning(f"Authorization failed for user {user_id} updating child {child_id}. Status: {authz_response.status_code}")
            return jsonify(authz_data), authz_response.status_code

    except (ConnectionError, TimeoutError, RequestException) as e:
         app.logger.error(f"Error checking authorization via db-interact: {e}")
         return jsonify({"message": "Error communicating with database service for authorization"}), 503
    except Exception as e:
         app.logger.error(f"Unexpected error during authorization check: {e}\n{traceback.format_exc()}")
         return jsonify({"message": "An internal server error occurred during authorization check"}), 500

    # --- If Authorized, Proceed with Update ---
    try:
        # Call the internal update endpoint in db-interact
        update_response = request_update_child(child_id, data, user_token)

        try: update_response_data = update_response.json()
        except requests.exceptions.JSONDecodeError: update_response_data = {"message": update_response.text}

        # Forward status code and data/message from db-interact
        return jsonify(update_response_data), update_response.status_code

    except (ConnectionError, TimeoutError, RequestException) as e:
        app.logger.error(f"Error communicating with db-interact service for update: {e}")
        return jsonify({"message": "Error communicating with database service for update"}), 503
    except Exception as e:
        app.logger.error(f"Unexpected error in update_child: {e}\n{traceback.format_exc()}")
        return jsonify({"message": "An internal server error occurred during update"}), 500

# Add DELETE /profiles/children/{child_id} if needed, with similar authorization checks

# --- Main Execution ---
if __name__ == '__main__':
    # Run the Flask app
    # Use port 5002 based on previous run.py example
    # Set debug=False in production
    app.run(host='0.0.0.0', port=5002, debug=True)

