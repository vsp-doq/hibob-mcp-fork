from fastmcp import FastMCP
import requests
import os

# Create a server instance
mcp = FastMCP(name="Hibob Public MCP")

# Module-level caches (persist for the lifetime of the MCP subprocess)
_field_metadata_cache = None
_named_lists_cache = {}

def _hibob_api_call(endpoint: str, body: dict = None, method: str = "POST", params: dict = None) -> dict:
    """Helper to call the HiBob API with proper headers, supporting GET, POST, PUT, PATCH, and DELETE."""
    url = f"https://api.hibob.com/v1/{endpoint}"
    hibob_token = os.environ.get("HIBOB_API_TOKEN", "")
    headers = {
        'authorization': f'Basic {hibob_token}',
        'content-type': 'application/json',
        'X-Request-Source': 'hibob-public-mcp'
    }
    if method == "GET":
        response = requests.get(url, headers=headers, params=params)
    elif method == "POST":
        response = requests.post(url, json=body, headers=headers, params=params)
    elif method == "PUT":
        response = requests.put(url, json=body, headers=headers, params=params)
    elif method == "PATCH":
        response = requests.patch(url, json=body, headers=headers, params=params)
    elif method == "DELETE":
        response = requests.delete(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

def _get_field_metadata():
    """Fetch field metadata, cached for the lifetime of the MCP subprocess."""
    global _field_metadata_cache
    if _field_metadata_cache is None:
        try:
            _field_metadata_cache = _hibob_api_call("company/people/fields", method="GET")
        except Exception:
            _field_metadata_cache = []
    return _field_metadata_cache

def _get_named_list(list_id: str) -> dict:
    """Fetch a named list by ID, cached for the lifetime of the MCP subprocess."""
    global _named_lists_cache
    if list_id not in _named_lists_cache:
        try:
            _named_lists_cache[list_id] = _hibob_api_call(f"company/named-lists/{list_id}", method="GET")
        except Exception:
            _named_lists_cache[list_id] = {}
    return _named_lists_cache[list_id]

def _resolve_list_values(employees: list, requested_fields: list) -> list:
    """Resolve numeric list-field IDs to human-readable display values using company named-lists."""
    if not employees or not requested_fields:
        return employees

    fields_meta = _get_field_metadata()
    if not fields_meta:
        return employees

    # Find list-type fields among the requested fields
    list_field_map = {}  # field_id -> listId
    for field in fields_meta:
        if not isinstance(field, dict):
            continue
        if field.get("type") in ("list", "multi-list", "hierarchy-list"):
            field_id = field.get("id", "")
            if field_id in requested_fields:
                list_id = (field.get("typeData") or {}).get("listId")
                if list_id:
                    list_field_map[field_id] = list_id

    if not list_field_map:
        return employees

    # Build ID → display-value mappings from named lists
    id_to_display = {}
    for field_id, list_id in list_field_map.items():
        list_data = _get_named_list(list_id)
        for item in list_data.get("values", []):
            item_id = str(item.get("id", ""))
            display = item.get("value") or item.get("name", "")
            if item_id and display:
                id_to_display[item_id] = display

    if not id_to_display:
        return employees

    # Replace numeric IDs in employee records (both dotted and slash-prefixed formats)
    for emp in employees:
        for field_id in list_field_map:
            parts = field_id.split(".")
            if len(parts) == 2:
                cat, fname = parts
                # Resolve dotted format: emp["work"]["title"] = "253271839" → "CEO"
                if isinstance(emp.get(cat), dict) and fname in emp[cat]:
                    raw = str(emp[cat][fname])
                    if raw in id_to_display:
                        emp[cat][fname] = id_to_display[raw]
                # Resolve slash-prefixed format: emp["/work/title"]["value"] = "253271839" → "CEO"
                slash_key = f"/{cat}/{fname}"
                if isinstance(emp.get(slash_key), dict) and "value" in emp[slash_key]:
                    raw = str(emp[slash_key]["value"])
                    if raw in id_to_display:
                        emp[slash_key]["value"] = id_to_display[raw]

    return employees

@mcp.tool()
def hibob_people_search(fields: list = None, filters: list = None, humanReadable: str = None) -> dict:
    """
    Search for employees in HiBob using advanced filters.

    Parameters:
        fields (list, optional): List of field paths to return for each employee. Use hibob_get_employee_fields to discover available fields.
        filters (list, optional): filter by ID or email. Options - 
        Example filter usage:
        filters = [
            {
                "fieldPath": "root.id",
                "operator": "equals",
                "values": ["EMPLOYEE_ID"]
            }
        ] 
        OR
        filters = [
            {
                "fieldPath": "root.email",
                "operator": "equals",
                "values": ["bla@example.com"]
            }
        ]

        to find employee by name you need to fetch with empty filters and then filter by name by yourself.

        humanReadable (str, optional): Pass "REPLACE" to get human-readable display
            names for list fields (e.g. work.title, work.department) instead of
            numeric IDs. When set to "APPEND", both the ID and display name are
            returned. Default is None (numeric IDs only).

    To get available field paths for fields, use the hibob_get_employee_fields tool.
    """
    body = {}
    if fields:
        body["fields"] = fields
    if filters:
        body["filters"] = filters
    result = _hibob_api_call("people/search", body)
    if humanReadable and fields:
        result["employees"] = _resolve_list_values(result.get("employees", []), fields)
        # Sort employees: reportsTo=null first (top-level leadership visible before truncation)
        employees = result.get("employees", [])
        result["employees"] = sorted(
            employees,
            key=lambda e: 0 if (isinstance(e.get("work"), dict) and e["work"].get("reportsTo") is None) else 1
        )
    return result

@mcp.tool()
def hibob_get_employee_fields() -> dict:
    """
    Get metadata about all employee fields from HiBob.
    Use this tool to discover available field paths for use in filters in hibob_people_search.
    """
    return _hibob_api_call("company/people/fields", method="GET")

@mcp.tool()
def hibob_update_employee(employeeId: str, fields: dict) -> dict:
    """
    Update specific fields in an employee's record in HiBob.
    Only employee fields are supported; table updates are not allowed via this endpoint.
    Parameters:
        employeeId (string, mandatory): List of field paths to return for each employee. Use hibob_get_employee_fields to discover available fields.
        fields (dict, mandatory): object with field to value for update. example: {"root.firstName": "NewName"}
    Example usage:
        hibob_update_employee("EMPLOYEE_ID", {"root.firstName": "NewName"})
    To get available field for filters and fields, use the hibob_get_employee_fields tool.
    See: https://apidocs.hibob.com/reference/put_people-identifier
    """
    endpoint = f"people/{employeeId}"
    return _hibob_api_call(endpoint, body=fields, method="PUT")

@mcp.tool()
def hibob_get_timeoff_policy_types() -> dict:
    """
    Get a list of all timeoff policy type names from HiBob.
    See: https://apidocs.hibob.com/reference/get_timeoff-policy-types
    """
    return _hibob_api_call("timeoff/policy-types", method="GET")

@mcp.tool()
def hibob_submit_timeoff_request(employee_id: str, request_details: dict) -> dict:
    """
    Submit a new time off request for an employee in HiBob.
    
    Parameters:
        employee_id (str): The HiBob employee ID.
        request_details (dict): The request body as required by the API. See the API docs for required fields for each request type.
            Common parameters for a Holiday request include:
                - type (str): The time off type, e.g., "Holiday"
                - requestRangeType: Value must be 'days'. mandatory.
                - startDatePortion: Value must be 'all_day'. mandatory.
                - endDatePortion: Value must be 'all_day'. mandatory.
                - startDate (str): Start date in YYYY-MM-DD format
                - endDate (str): End date in YYYY-MM-DD format
                - days (float): Number of days requested
                - reason (str, optional): Reason for the request
                - comment (str, optional): Additional comments
                - halfDay (bool, optional): If the request is for a half day
                - policyType (str, optional): Policy type name
                - reasonCode (str, optional): Reason code if required by policy

            Example:
                hibob_submit_timeoff_request(
                    "EMPLOYEE_ID",
                    {
                        "type": "Holiday",
                        "startDate": "2024-07-01",
                        "endDate": "2024-07-05",
                        "startDatePortion": 'all_day',
                        "endDatePortion": 'all_day',
                        "requestRangeType": 'days',
                        "reason": "Vacation",
                        "comment": "Family trip",
                        "halfDay": False
                    }
                )
    
    See: https://apidocs.hibob.com/reference/post_timeoff-employees-id-requests
    """
    endpoint = f"timeoff/employees/{employee_id}/requests"
    return _hibob_api_call(endpoint, body=request_details, method="POST")

@mcp.tool()
def hibob_create_employee(fields: dict) -> dict:
    """
    Create a new employee record in HiBob.

    Parameters:
        fields (dict): Dictionary of employee fields to set. Only fields listed in the Fields Metadata API are allowed.
        check that you have site and startDate which are manadatory

    Example usage:
        hibob_create_employee({
            "root.firstName": "Jane",
            "root.surname": "Doe",
            "root.email": "jane.doe@example.com"
        })

    See: https://apidocs.hibob.com/reference/post_people
    """
    return _hibob_api_call("people", body=fields, method="POST")

@mcp.tool()
def hibob_get_employee_tasks(employee_id: str) -> dict:
    """
    Get all tasks for a specific employee in HiBob.

    Parameters:
        employee_id (str): The HiBob employee ID.

    Example usage:
        hibob_get_employee_tasks("EMPLOYEE_ID")

    See: https://apidocs.hibob.com/reference/get_tasks-people-id
    """
    endpoint = f"tasks/people/{employee_id}"
    return _hibob_api_call(endpoint, method="GET")

# ===============================
# Goals API Tools
# ===============================

@mcp.tool()
def hibob_get_goal_types_metadata() -> dict:
    """
    Get metadata for goal types in HiBob Goals API.
    This provides field definitions and metadata for goal type objects.

    See: https://apidocs.hibob.com/reference/get_goals-goal-types-metadata
    """
    return _hibob_api_call("goals/goal-types/metadata", method="GET")

@mcp.tool()
def hibob_get_goals_metadata() -> dict:
    """
    Get metadata for goals in HiBob Goals API.
    This provides field definitions and metadata for goal objects.

    See: https://apidocs.hibob.com/reference/get_goals-goals-metadata
    """
    return _hibob_api_call("goals/goals/metadata", method="GET")

@mcp.tool()
def hibob_get_key_results_metadata() -> dict:
    """
    Get metadata for key results in HiBob Goals API.
    This provides field definitions and metadata for key result objects.

    See: https://apidocs.hibob.com/reference/get_goals-goals-key-results-metadata
    """
    return _hibob_api_call("goals/goals/key-results/metadata", method="GET")

@mcp.tool()
def hibob_search_goal_types(fields: list = None, filters: list = None) -> dict:
    """
    Search for goal types in HiBob using filters.

    Parameters:
        fields (list, optional): List of field paths to return for each goal type.
        filters (list, optional): List of filter objects to apply to the search.

    Example usage:
        hibob_search_goal_types(
            fields=["id", "name", "description"],
            filters=[{"fieldPath": "name", "operator": "equals", "values": ["OKR"]}]
        )

    Use hibob_get_goal_types_metadata() to discover available fields.
    See: https://apidocs.hibob.com/reference/post_goals-goal-types-search
    """
    body = {}
    if fields:
        body["fields"] = fields
    if filters:
        body["filters"] = filters
    return _hibob_api_call("goals/goal-types/search", body)

@mcp.tool()
def hibob_search_goals(fields: list = None, filters: list = None) -> dict:
    """
    Search for goals in HiBob using filters.

    Parameters:
        fields (list, optional): List of field paths to return for each goal.
        filters (list, optional): List of filter objects to apply to the search.

    Example usage:
        hibob_search_goals(
            fields=["id", "title", "status", "owner"],
            filters=[{"fieldPath": "status", "operator": "equals", "values": ["active"]}]
        )

    Use hibob_get_goals_metadata() to discover available fields.
    See: https://apidocs.hibob.com/reference/post_goals-goals-search
    """
    body = {}
    if fields:
        body["fields"] = fields
    if filters:
        body["filters"] = filters
    return _hibob_api_call("goals/goals/search", body)

@mcp.tool()
def hibob_search_key_results(fields: list = None, filters: list = None) -> dict:
    """
    Search for key results in HiBob using filters.

    Parameters:
        fields (list, optional): List of field paths to return for each key result.
        filters (list, optional): List of filter objects to apply to the search.

    Example usage:
        hibob_search_key_results(
            fields=["id", "title", "progress", "target"],
            filters=[{"fieldPath": "goalId", "operator": "equals", "values": ["GOAL_ID"]}]
        )

    Use hibob_get_key_results_metadata() to discover available fields.
    See: https://apidocs.hibob.com/reference/post_goals-goals-key-results-search
    """
    body = {}
    if fields:
        body["fields"] = fields
    if filters:
        body["filters"] = filters
    return _hibob_api_call("goals/goals/key-results/search", body)

@mcp.tool()
def hibob_create_goal(goal_data: dict) -> dict:
    """
    Create a new goal in HiBob.

    Parameters:
        goal_data (dict): The goal data including title, description, owner, etc.

    Example usage:
        hibob_create_goal({
            "title": "Increase customer satisfaction",
            "description": "Improve customer satisfaction scores by 15%",
            "owner": "EMPLOYEE_ID",
            "goalType": "GOAL_TYPE_ID",
            "startDate": "2024-01-01",
            "endDate": "2024-12-31"
        })

    Use hibob_get_goals_metadata() to discover required and available fields.
    See: https://apidocs.hibob.com/reference/post_goals-goals
    """
    return _hibob_api_call("goals/goals", goal_data)

@mcp.tool()
def hibob_update_goal_status(goal_id: str, status_data: dict) -> dict:
    """
    Update the status of a goal in HiBob.

    Parameters:
        goal_id (str): The ID of the goal to update.
        status_data (dict): The status update data.

    Example usage:
        hibob_update_goal_status("GOAL_ID", {
            "status": "completed",
            "comments": "Goal successfully achieved"
        })

    See: https://apidocs.hibob.com/reference/patch_goals-goals-goalid-status
    """
    endpoint = f"goals/goals/{goal_id}/status"
    return _hibob_api_call(endpoint, status_data, method="PATCH")

@mcp.tool()
def hibob_update_goal(goal_id: str, goal_data: dict) -> dict:
    """
    Update a goal in HiBob.

    Parameters:
        goal_id (str): The ID of the goal to update.
        goal_data (dict): The updated goal data.

    Example usage:
        hibob_update_goal("GOAL_ID", {
            "title": "Updated goal title",
            "description": "Updated description"
        })

    Use hibob_get_goals_metadata() to discover available fields.
    See: https://apidocs.hibob.com/reference/patch_goals-goals-goalid
    """
    endpoint = f"goals/goals/{goal_id}"
    return _hibob_api_call(endpoint, goal_data, method="PATCH")

@mcp.tool()
def hibob_delete_goal(goal_id: str) -> dict:
    """
    Delete a goal from HiBob.

    Parameters:
        goal_id (str): The ID of the goal to delete.

    Example usage:
        hibob_delete_goal("GOAL_ID")

    See: https://apidocs.hibob.com/reference/delete_goals-goals-goalid
    """
    endpoint = f"goals/goals/{goal_id}"
    return _hibob_api_call(endpoint, method="DELETE")

@mcp.tool()
def hibob_create_key_results(goal_id: str, key_results_data: dict) -> dict:
    """
    Create key results for a goal in HiBob.

    Parameters:
        goal_id (str): The ID of the goal to add key results to.
        key_results_data (dict): The key results data.

    Example usage:
        hibob_create_key_results("GOAL_ID", {
            "keyResults": [
                {
                    "title": "Achieve 95% customer satisfaction score",
                    "description": "Measured via quarterly surveys",
                    "target": 95,
                    "unit": "percentage",
                    "startValue": 85
                }
            ]
        })

    Use hibob_get_key_results_metadata() to discover required and available fields.
    See: https://apidocs.hibob.com/reference/post_goals-goals-goalid-key-results
    """
    endpoint = f"goals/goals/{goal_id}/key-results"
    return _hibob_api_call(endpoint, key_results_data)

@mcp.tool()
def hibob_update_key_results_progress(goal_id: str, progress_data: dict) -> dict:
    """
    Update the progress of key results for a goal in HiBob.

    Parameters:
        goal_id (str): The ID of the goal containing the key results.
        progress_data (dict): The progress update data.

    Example usage:
        hibob_update_key_results_progress("GOAL_ID", {
            "keyResults": [
                {
                    "id": "KEY_RESULT_ID",
                    "currentValue": 90,
                    "comments": "Good progress this quarter"
                }
            ]
        })

    See: https://apidocs.hibob.com/reference/patch_goals-goals-goalid-key-results-progress
    """
    endpoint = f"goals/goals/{goal_id}/key-results/progress"
    return _hibob_api_call(endpoint, progress_data, method="PATCH")

@mcp.tool()
def hibob_update_key_results_details(goal_id: str, details_data: dict) -> dict:
    """
    Update the details of key results for a goal in HiBob.

    Parameters:
        goal_id (str): The ID of the goal containing the key results.
        details_data (dict): The key results details update data.

    Example usage:
        hibob_update_key_results_details("GOAL_ID", {
            "keyResults": [
                {
                    "id": "KEY_RESULT_ID",
                    "title": "Updated key result title",
                    "description": "Updated description",
                    "target": 100
                }
            ]
        })

    Use hibob_get_key_results_metadata() to discover available fields.
    See: https://apidocs.hibob.com/reference/patch_goals-goals-goalid-key-results
    """
    endpoint = f"goals/goals/{goal_id}/key-results"
    return _hibob_api_call(endpoint, details_data, method="PATCH")

@mcp.tool()
def hibob_delete_key_result(goal_id: str, key_result_id: str) -> dict:
    """
    Delete a key result from a goal in HiBob.

    Parameters:
        goal_id (str): The ID of the goal containing the key result.
        key_result_id (str): The ID of the key result to delete.

    Example usage:
        hibob_delete_key_result("GOAL_ID", "KEY_RESULT_ID")

    See: https://apidocs.hibob.com/reference/delete_goals-goals-goalid-key-results-keyresultid
    """
    endpoint = f"goals/goals/{goal_id}/key-results/{key_result_id}"
    return _hibob_api_call(endpoint, method="DELETE")

if __name__ == "__main__":
    mcp.run(transport="stdio")
