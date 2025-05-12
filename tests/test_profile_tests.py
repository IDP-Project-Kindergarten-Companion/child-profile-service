# tests/test_profile_routes.py
import pytest
import requests
import time
import uuid # To generate unique usernames/emails for each run
import os

# --- Configuration ---
# URLs are now handled by fixtures in conftest.py

# --- Test Data ---
def generate_unique_user(role="parent"):
    """Generates unique user data for testing."""
    unique_id = str(uuid.uuid4())[:8]
    if role == "parent":
        return {
            "username": f"cptest_parent_{unique_id}",
            "password": "password123",
            "role": "parent",
            "email": f"cptest_parent_{unique_id}@example.com",
            "first_name": "CPParent",
            "last_name": unique_id
        }
    else: # teacher
        return {
            "username": f"cptest_teacher_{unique_id}",
            "password": "password456",
            "role": "teacher",
            "email": f"cptest_teacher_{unique_id}@example.com",
            "first_name": "CPTeacher",
            "last_name": unique_id
        }

CHILD_DATA_TEMPLATE = {
    "name": "CP Test Child",
    "birthday": "2023-01-10",
    "group": "Apples",
    "allergies": ["Testing"],
    "notes": "Child profile test subject"
}

# --- Fixtures ---

# Fixture to register and log in users (Session scope is usually fine)
@pytest.fixture(scope="session")
def test_users_logged_in(http_session, auth_service_url):
    """Registers and logs in a parent and teacher user ONCE."""
    print("\nSetting up and logging in test users (session scope)...")
    parent_data = generate_unique_user("parent")
    teacher_data = generate_unique_user("teacher")
    users = {"parent": {}, "teacher": {}}

    # Register and Login Parent
    try:
        reg_resp = http_session.post(f"{auth_service_url}/auth/register", json=parent_data, timeout=10)
        if reg_resp.status_code not in [201, 409]: # Allow if already exists
             pytest.fail(f"Parent registration failed: {reg_resp.status_code} - {reg_resp.text}")

        login_resp = http_session.post(f"{auth_service_url}/auth/login", json={"username": parent_data["username"], "password": parent_data["password"]})
        login_resp.raise_for_status() # Fail if login doesn't work
        login_data = login_resp.json()
        users["parent"]["token"] = login_data.get("access_token")
        users["parent"]["id"] = login_data.get("user_id")
        assert users["parent"]["token"] and users["parent"]["id"]
        print(f"Parent logged in: {parent_data['username']} ({users['parent']['id']})")
    except Exception as e:
        pytest.fail(f"Parent setup failed: {e}")

    # Register and Login Teacher
    try:
        reg_resp = http_session.post(f"{auth_service_url}/auth/register", json=teacher_data, timeout=10)
        if reg_resp.status_code not in [201, 409]:
             pytest.fail(f"Teacher registration failed: {reg_resp.status_code} - {reg_resp.text}")

        login_resp = http_session.post(f"{auth_service_url}/auth/login", json={"username": teacher_data["username"], "password": teacher_data["password"]})
        login_resp.raise_for_status()
        login_data = login_resp.json()
        users["teacher"]["token"] = login_data.get("access_token")
        users["teacher"]["id"] = login_data.get("user_id")
        assert users["teacher"]["token"] and users["teacher"]["id"]
        print(f"Teacher logged in: {teacher_data['username']} ({users['teacher']['id']})")
    except Exception as e:
        pytest.fail(f"Teacher setup failed: {e}")

    return users

# Fixture to create a child and get the linking code (Function scope for isolation)
@pytest.fixture(scope="function")
def created_child_with_code(test_users_logged_in, child_profile_url, http_session):
    """Creates a child using the parent token and returns child_id and linking_code."""
    print("\nCreating child and getting linking code (function scope)...")
    parent_token = test_users_logged_in["parent"]["token"]
    headers = {"Authorization": f"Bearer {parent_token}"}
    endpoint = "/profiles/children"

    response = http_session.post(f"{child_profile_url}{endpoint}", headers=headers, json=CHILD_DATA_TEMPLATE)
    assert response.status_code == 201, f"Child creation failed: {response.status_code} - {response.text}"
    response_data = response.json()
    child_id = response_data.get("child_id")
    linking_code = response_data.get("linking_code")
    assert child_id and linking_code, "Child creation response missing child_id or linking_code"
    print(f"Child created: {child_id}, Code: {linking_code[:10]}...") # Print partial code
    return {"child_id": child_id, "linking_code": linking_code}


# --- Test Functions ---

def test_add_child_unauthorized(test_users_logged_in, child_profile_url, http_session):
    """Verify only parents can add children."""
    print("\nTesting POST /profiles/children unauthorized (as Teacher)...")
    teacher_token = test_users_logged_in["teacher"]["token"]
    headers = {"Authorization": f"Bearer {teacher_token}"}
    endpoint = "/profiles/children"

    response = http_session.post(f"{child_profile_url}{endpoint}", headers=headers, json=CHILD_DATA_TEMPLATE)
    assert response.status_code == 403, f"Expected 403 Forbidden, got {response.status_code}"
    print("Add child as teacher: Forbidden (OK)")

def test_add_child_success(test_users_logged_in, child_profile_url, http_session):
    """Test successful child creation by a parent."""
    # This implicitly uses the created_child_with_code fixture logic via other tests,
    # but we can test it explicitly here too.
    print("\nTesting POST /profiles/children success (as Parent)...")
    parent_token = test_users_logged_in["parent"]["token"]
    headers = {"Authorization": f"Bearer {parent_token}"}
    endpoint = "/profiles/children"
    # Use slightly different data to avoid potential conflicts if run fast
    child_data = CHILD_DATA_TEMPLATE.copy()
    child_data["name"] = "CP Test Child Success"

    response = http_session.post(f"{child_profile_url}{endpoint}", headers=headers, json=child_data)
    assert response.status_code == 201, f"Child creation failed: {response.status_code} - {response.text}"
    response_data = response.json()
    assert "child_id" in response_data
    assert "linking_code" in response_data
    print("Add child as parent: Success (OK)")


def test_link_supervisor(test_users_logged_in, created_child_with_code, child_profile_url, http_session):
    """Test linking a supervisor using the generated code."""
    print("\nTesting POST /profiles/children/link-supervisor...")
    teacher_token = test_users_logged_in["teacher"]["token"]
    linking_code = created_child_with_code["linking_code"]
    expected_child_id = created_child_with_code["child_id"]
    headers = {"Authorization": f"Bearer {teacher_token}"}
    endpoint = "/profiles/children/link-supervisor"
    payload = {"linking_code": linking_code}

    response = http_session.post(f"{child_profile_url}{endpoint}", headers=headers, json=payload)
    assert response.status_code == 200, f"Supervisor linking failed: {response.status_code} - {response.text}"
    response_data = response.json()
    assert response_data.get("message") == "Supervisor linked successfully"
    assert response_data.get("child_id") == expected_child_id
    print("Link supervisor: Success (OK)")

    # --- Verification: Try getting child data as the now-linked teacher ---
    print("Verifying link by getting child data as teacher...")
    time.sleep(0.5) # Allow potential eventual consistency
    verify_endpoint = f"/profiles/children/{expected_child_id}"
    verify_response = http_session.get(f"{child_profile_url}{verify_endpoint}", headers=headers)
    assert verify_response.status_code == 200, f"Failed to get child data after linking: {verify_response.text}"
    assert verify_response.json()["_id"] == expected_child_id
    print("Link verification via GET: Success (OK)")


def test_link_supervisor_invalid_code(test_users_logged_in, child_profile_url, http_session):
    """Test linking with an invalid/expired code."""
    print("\nTesting POST /profiles/children/link-supervisor (Invalid Code)...")
    teacher_token = test_users_logged_in["teacher"]["token"]
    headers = {"Authorization": f"Bearer {teacher_token}"}
    endpoint = "/profiles/children/link-supervisor"
    payload = {"linking_code": "this_is_not_a_valid_jwt_code"}

    response = http_session.post(f"{child_profile_url}{endpoint}", headers=headers, json=payload)
    # Expect 400 Bad Request because the code verification fails
    assert response.status_code == 400, f"Expected 400 for invalid code, got {response.status_code}"
    assert "Invalid or expired linking code" in response.json().get("message", "")
    print("Link supervisor invalid code: Bad Request (OK)")

def test_link_supervisor_unauthorized_role(test_users_logged_in, created_child_with_code, child_profile_url, http_session):
    """Test linking attempt by a parent (wrong role)."""
    print("\nTesting POST /profiles/children/link-supervisor (as Parent)...")
    parent_token = test_users_logged_in["parent"]["token"]
    linking_code = created_child_with_code["linking_code"]
    headers = {"Authorization": f"Bearer {parent_token}"}
    endpoint = "/profiles/children/link-supervisor"
    payload = {"linking_code": linking_code}

    response = http_session.post(f"{child_profile_url}{endpoint}", headers=headers, json=payload)
    assert response.status_code == 403, f"Expected 403 Forbidden, got {response.status_code}"
    print("Link supervisor as parent: Forbidden (OK)")


# This test depends on the linking succeeding in test_link_supervisor
# We use the created_child_with_code fixture again to get a fresh child for this test
def test_get_child_after_linking(test_users_logged_in, created_child_with_code, child_profile_url, http_session):
    """Verify parent and linked teacher can get child data."""
    # First, link the supervisor for this specific child instance
    child_id = created_child_with_code["child_id"]
    linking_code = created_child_with_code["linking_code"]
    teacher_token = test_users_logged_in["teacher"]["token"]
    teacher_id = test_users_logged_in["ids"]["teacher"]
    parent_token = test_users_logged_in["parent"]["token"]
    link_headers = {"Authorization": f"Bearer {teacher_token}"}
    link_payload = {"linking_code": linking_code}
    link_resp = http_session.post(f"{child_profile_url}/profiles/children/link-supervisor", headers=link_headers, json=link_payload)
    assert link_resp.status_code == 200, "Pre-test linking failed"
    print(f"\nPre-test link confirmed for child {child_id}")
    time.sleep(0.5) # Allow time for update

    print(f"\nTesting GET /profiles/children/{child_id} (after linking)...")
    endpoint = f"/profiles/children/{child_id}"

    # Test as Parent
    headers_parent = {"Authorization": f"Bearer {parent_token}"}
    response_parent = http_session.get(f"{child_profile_url}{endpoint}", headers=headers_parent)
    assert response_parent.status_code == 200, f"Parent failed GET after link: {response_parent.text}"
    assert response_parent.json()["_id"] == child_id
    print("Get child as Parent: OK")

    # Test as Teacher
    headers_teacher = {"Authorization": f"Bearer {teacher_token}"}
    response_teacher = http_session.get(f"{child_profile_url}{endpoint}", headers=headers_teacher)
    assert response_teacher.status_code == 200, f"Teacher failed GET after link: {response_teacher.text}"
    assert response_teacher.json()["_id"] == child_id
    # Verify teacher ID is now in the list returned by the profile service
    assert teacher_id in response_teacher.json().get("supervisor_ids", [])
    print("Get child as Teacher: OK")

def test_get_child_unauthorized(test_users_logged_in, second_parent_user, created_child_with_code, child_profile_url, http_session):
    """Verify an unlinked user cannot get child data."""
    print("\nTesting GET /profiles/children/{child_id} (Unauthorized User)...")
    child_id = created_child_with_code["child_id"] # Child created by first parent
    unauthorized_token = second_parent_user["token"] # Token from a different parent
    headers = {"Authorization": f"Bearer {unauthorized_token}"}
    endpoint = f"/profiles/children/{child_id}"

    response = http_session.get(f"{child_profile_url}{endpoint}", headers=headers)
    assert response.status_code == 403, f"Expected 403 Forbidden, got {response.status_code}"
    print("Get child as unauthorized user: Forbidden (OK)")


def test_update_child(test_users_logged_in, linked_child_supervisor, child_profile_url, http_session):
    """Test updating child details as an authorized user (parent)."""
    print("\nTesting PUT /profiles/children/{child_id}...")
    parent_token = test_users_logged_in["parent"]["token"]
    child_id = linked_child_supervisor # Use child ID where supervisor is linked
    headers = {"Authorization": f"Bearer {parent_token}"}
    endpoint = f"/profiles/children/{child_id}"
    update_payload = {"group": "Explorers", "notes": "Updated via PUT test"}

    # Perform Update
    response_update = http_session.put(f"{child_profile_url}{endpoint}", headers=headers, json=update_payload)
    assert response_update.status_code == 200, f"Update child failed: {response_update.text}"
    assert "updated" in response_update.json().get("message", "").lower()
    print("Update child API call: OK")

    # Verify Update
    time.sleep(0.5)
    response_verify = http_session.get(f"{child_profile_url}{endpoint}", headers=headers)
    assert response_verify.status_code == 200
    updated_data = response_verify.json()
    assert updated_data["group"] == "Explorers"
    assert updated_data["notes"] == "Updated via PUT test"
    print("Verify child update: OK")

def test_update_child_unauthorized(test_users_logged_in, second_parent_user, created_child_with_code, child_profile_url, http_session):
    """Test updating child details as an unauthorized user."""
    print("\nTesting PUT /profiles/children/{child_id} (Unauthorized)...")
    unauthorized_token = second_parent_user["token"]
    child_id = created_child_with_code["child_id"]
    headers = {"Authorization": f"Bearer {unauthorized_token}"}
    endpoint = f"/profiles/children/{child_id}"
    update_payload = {"notes": "Unauthorized update attempt"}

    response_update = http_session.put(f"{child_profile_url}{endpoint}", headers=headers, json=update_payload)
    assert response_update.status_code == 403, f"Expected 403 Forbidden, got {response_update.status_code}"
    print("Update child unauthorized: Forbidden (OK)")

