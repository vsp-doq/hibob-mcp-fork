from fastmcp import FastMCP
import requests
import os
import time

mcp = FastMCP(name="Hibob Public MCP")

_field_metadata_cache = None
_named_lists_cache = {}
_employee_cache = None
_employee_cache_ts = 0
_EMPLOYEE_CACHE_TTL = 300

_STANDARD_FIELDS = [
    "root.id", "root.firstName", "root.surname", "root.email",
    "work.title", "work.department", "work.site", "work.reportsTo",
    "work.startDate",
]


def _hibob_api_call(endpoint: str, body: dict = None, method: str = "POST", params: dict = None) -> dict:
    url = f"https://api.hibob.com/v1/{endpoint}"
    hibob_token = os.environ.get("HIBOB_API_TOKEN", "")
    headers = {
        "authorization": f"Basic {hibob_token}",
        "content-type": "application/json",
        "X-Request-Source": "hibob-public-mcp",
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
    global _field_metadata_cache
    if _field_metadata_cache is None:
        try:
            _field_metadata_cache = _hibob_api_call("company/people/fields", method="GET")
        except Exception:
            _field_metadata_cache = []
    return _field_metadata_cache


def _get_named_list(list_id: str) -> dict:
    global _named_lists_cache
    if list_id not in _named_lists_cache:
        try:
            _named_lists_cache[list_id] = _hibob_api_call(f"company/named-lists/{list_id}", method="GET")
        except Exception:
            _named_lists_cache[list_id] = {}
    return _named_lists_cache[list_id]


def _resolve_list_values(employees: list, requested_fields: list) -> list:
    if not employees or not requested_fields:
        return employees

    fields_meta = _get_field_metadata()
    if not fields_meta:
        return employees

    list_field_map = {}
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

    for emp in employees:
        for field_id in list_field_map:
            parts = field_id.split(".")
            if len(parts) == 2:
                cat, fname = parts
                if isinstance(emp.get(cat), dict) and fname in emp[cat]:
                    raw = str(emp[cat][fname])
                    if raw in id_to_display:
                        emp[cat][fname] = id_to_display[raw]
                slash_key = f"/{cat}/{fname}"
                if isinstance(emp.get(slash_key), dict) and "value" in emp[slash_key]:
                    raw = str(emp[slash_key]["value"])
                    if raw in id_to_display:
                        emp[slash_key]["value"] = id_to_display[raw]

    return employees


def _get_field(emp: dict, category: str, field_name: str):
    cat_data = emp.get(category)
    if isinstance(cat_data, dict) and field_name in cat_data:
        return cat_data[field_name]
    slash_key = f"/{category}/{field_name}"
    slash_data = emp.get(slash_key)
    if isinstance(slash_data, dict) and "value" in slash_data:
        return slash_data["value"]
    return None


def _compact_display(emp: dict) -> str:
    first = _get_field(emp, "root", "firstName") or ""
    last = _get_field(emp, "root", "surname") or ""
    email = _get_field(emp, "root", "email") or ""
    title = _get_field(emp, "work", "title") or ""
    dept = _get_field(emp, "work", "department") or ""
    site = _get_field(emp, "work", "site") or ""

    name = f"{first} {last}".strip() or "(unnamed)"
    parts = [name]
    if title:
        parts.append(title)
    if dept:
        parts.append(dept)
    if site:
        parts.append(site)
    if email:
        parts.append(email)
    return " | ".join(parts)


def _get_all_employees() -> list:
    global _employee_cache, _employee_cache_ts
    if _employee_cache is not None and (time.time() - _employee_cache_ts) < _EMPLOYEE_CACHE_TTL:
        return _employee_cache

    body = {"fields": _STANDARD_FIELDS}
    result = _hibob_api_call("people/search", body)
    employees = result.get("employees", [])
    employees = _resolve_list_values(employees, _STANDARD_FIELDS)
    _employee_cache = employees
    _employee_cache_ts = time.time()
    return employees


def _employee_profile(emp: dict) -> str:
    eid = _get_field(emp, "root", "id") or ""
    first = _get_field(emp, "root", "firstName") or ""
    last = _get_field(emp, "root", "surname") or ""
    email = _get_field(emp, "root", "email") or ""
    title = _get_field(emp, "work", "title") or ""
    dept = _get_field(emp, "work", "department") or ""
    site = _get_field(emp, "work", "site") or ""
    start = _get_field(emp, "work", "startDate") or ""
    reports_to = ""
    work = emp.get("work", {})
    rt = work.get("reportsTo") if isinstance(work, dict) else None
    if rt and isinstance(rt, dict):
        rt_name = rt.get("displayName") or rt.get("email") or ""
        if rt_name:
            reports_to = rt_name

    name = f"{first} {last}".strip()
    lines = [f"Name: {name}"]
    if eid:
        lines.append(f"ID: {eid}")
    if email:
        lines.append(f"Email: {email}")
    if title:
        lines.append(f"Title: {title}")
    if dept:
        lines.append(f"Department: {dept}")
    if site:
        lines.append(f"Site: {site}")
    if start:
        lines.append(f"Start Date: {start}")
    if reports_to:
        lines.append(f"Reports To: {reports_to}")
    return "\n".join(lines)


def _match_employee(emp: dict, query: str) -> bool:
    q = query.lower()
    first = (_get_field(emp, "root", "firstName") or "").lower()
    last = (_get_field(emp, "root", "surname") or "").lower()
    email = (_get_field(emp, "root", "email") or "").lower()
    full_name = f"{first} {last}".strip()
    return q in full_name or q in email or q in first or q in last


@mcp.tool()
def hibob_get_employee(query: str) -> str:
    """Look up employees by name or email. Returns compact profile(s) with ID, title, department, site, start date, and manager.

    Parameters:
        query (str): Full or partial name, or email address to search for.
    """
    employees = _get_all_employees()
    matches = [e for e in employees if _match_employee(e, query)]

    if not matches:
        return f"No employees found matching '{query}'."

    if len(matches) == 1:
        return _employee_profile(matches[0])

    lines = [f"Found {len(matches)} employees matching '{query}':\n"]
    for emp in matches[:20]:
        lines.append(_employee_profile(emp))
        lines.append("")
    if len(matches) > 20:
        lines.append(f"... and {len(matches) - 20} more. Refine your query.")
    return "\n".join(lines)


@mcp.tool()
def hibob_get_team(department: str = None, site: str = None) -> str:
    """List employees filtered by department and/or site. Returns a compact list.

    Parameters:
        department (str, optional): Department name to filter by (case-insensitive partial match).
        site (str, optional): Site/office name to filter by (case-insensitive partial match).

    At least one filter must be provided.
    """
    if not department and not site:
        return "Error: Provide at least one filter (department or site)."

    employees = _get_all_employees()
    matches = employees

    if department:
        d = department.lower()
        matches = [e for e in matches if d in (_get_field(e, "work", "department") or "").lower()]

    if site:
        s = site.lower()
        matches = [e for e in matches if s in (_get_field(e, "work", "site") or "").lower()]

    if not matches:
        parts = []
        if department:
            parts.append(f"department='{department}'")
        if site:
            parts.append(f"site='{site}'")
        return f"No employees found for {', '.join(parts)}."

    lines = [f"Found {len(matches)} employees:\n"]
    for emp in matches:
        lines.append(_compact_display(emp))
    return "\n".join(lines)


@mcp.tool()
def hibob_get_org_chart() -> str:
    """Get the complete organizational hierarchy as a compact indented tree. Use for hierarchy, reporting lines, team structure, or manager lookups."""
    employees = _get_all_employees()

    emp_by_id = {}
    children = {}
    roots = []

    for emp in employees:
        emp_id = _get_field(emp, "root", "id")
        if not emp_id:
            continue
        emp_id = str(emp_id)
        emp_by_id[emp_id] = emp

        work = emp.get("work", {})
        reports_to = work.get("reportsTo") if isinstance(work, dict) else None

        if reports_to and isinstance(reports_to, dict):
            manager_id = str(reports_to.get("id", ""))
            if manager_id:
                children.setdefault(manager_id, []).append(emp_id)
            else:
                roots.append(emp_id)
        else:
            roots.append(emp_id)

    lines = [f"ORG CHART ({len(employees)} employees)\n"]

    def render_tree(eid, indent=0):
        emp = emp_by_id.get(eid)
        if not emp:
            return
        prefix = "  " * indent
        lines.append(f"{prefix}{_compact_display(emp)}")
        for child_id in sorted(children.get(eid, []),
                               key=lambda c: _compact_display(emp_by_id.get(c, {}))):
            render_tree(child_id, indent + 1)

    for root_id in sorted(roots, key=lambda r: _compact_display(emp_by_id.get(r, {}))):
        render_tree(root_id)

    return "\n".join(lines)


def _get_policy_type_names() -> list:
    try:
        result = _hibob_api_call("timeoff/policy-types", method="GET")
        if isinstance(result, list):
            return [pt.get("name", pt) if isinstance(pt, dict) else str(pt) for pt in result]
        if isinstance(result, dict) and "policyTypes" in result:
            return [pt.get("name", pt) if isinstance(pt, dict) else str(pt) for pt in result["policyTypes"]]
        return []
    except Exception:
        return []


@mcp.tool()
def hibob_get_timeoff_balance(employee_id: str, date: str = "") -> str:
    """Get time-off balance for an employee across all policy types.

    Parameters:
        employee_id (str): The HiBob employee ID.
        date (str, optional): Date for balance snapshot in YYYY-MM-DD format. Defaults to today.
    """
    from datetime import date as date_type
    balance_date = date if date else date_type.today().isoformat()

    policy_types = _get_policy_type_names()
    if not policy_types:
        return "Could not retrieve policy types. Check API permissions."

    lines = []
    for pt in policy_types:
        try:
            result = _hibob_api_call(
                f"timeoff/employees/{employee_id}/balance",
                method="GET",
                params={"policyType": pt, "date": balance_date},
            )
        except Exception:
            continue

        if not isinstance(result, dict):
            continue

        assignment = result.get("currentAssignment", "")
        if assignment == "Unassigned":
            continue

        policy_name = result.get("policy", pt)
        balance = result.get("totalBalanceAsOfDate", "?")
        taken = result.get("totalTaken", "?")
        allowance = result.get("annualAllowance", "?")
        lines.append(f"{policy_name}: {balance} remaining (taken {taken}, allowance {allowance})")

    if not lines:
        return f"No active time-off balances found for employee {employee_id} as of {balance_date}."

    return f"Time-off balances as of {balance_date}:\n" + "\n".join(lines)


def _format_out_entry(entry: dict) -> str:
    if not isinstance(entry, dict):
        return ""
    name = entry.get("employeeDisplayName", "Unknown")
    policy = entry.get("policyTypeDisplayName", "")
    status = entry.get("status", "")
    req_type = entry.get("type", "")

    start = entry.get("startDate", entry.get("date", ""))
    end = entry.get("endDate", "")

    parts = [name]
    if policy:
        parts.append(policy)
    if status and status != "approved":
        parts.append(f"[{status}]")
    if start and end:
        parts.append(f"{start} → {end}")
    elif start:
        parts.append(start)
    if req_type == "hours":
        hours = entry.get("hoursOnDate", "")
        if hours:
            parts.append(f"{hours}h")
    elif req_type == "portionOnRange":
        portion = entry.get("dayPortion", "")
        if portion:
            parts.append(portion)
    return " | ".join(parts)


@mcp.tool()
def hibob_whois_out(from_date: str, to_date: str) -> str:
    """Check who is out of office in a date range.

    Parameters:
        from_date (str): Start date in YYYY-MM-DD format.
        to_date (str): End date in YYYY-MM-DD format.
    """
    try:
        result = _hibob_api_call("timeoff/whosout", method="GET", params={
            "from": from_date, "to": to_date, "includePending": "true",
        })
    except Exception as e:
        return f"Error fetching who's out: {e}"

    outs = result.get("outs", []) if isinstance(result, dict) else (result if isinstance(result, list) else [])
    if not outs:
        return f"No one is out between {from_date} and {to_date}."

    lines = [f"Out of office ({from_date} to {to_date}): {len(outs)} entries\n"]
    for entry in outs:
        line = _format_out_entry(entry)
        if line:
            lines.append(line)
    return "\n".join(lines)


def _format_today_entry(entry: dict) -> str:
    if not isinstance(entry, dict):
        return ""
    name = entry.get("employeeDisplayName", "Unknown")
    policy = entry.get("policyTypeDisplayName", "")
    req_type = entry.get("requestRangeType", "")

    start = entry.get("startDate", "")
    end = entry.get("endDate", "")

    parts = [name]
    if policy:
        parts.append(policy)
    if start and end:
        parts.append(f"{start} → {end}")
    elif start:
        parts.append(start)
    if req_type == "hours":
        hours = entry.get("hours", "")
        mins = entry.get("minutes", 0)
        if hours:
            parts.append(f"{hours}h{mins}m" if mins else f"{hours}h")
    elif req_type == "portionOnRange":
        portion = entry.get("dayPortion", "")
        if portion:
            parts.append(portion)
    elif req_type == "hoursOnRange":
        daily = entry.get("dailyHours", "")
        if daily:
            parts.append(f"{daily}h/day")
    return " | ".join(parts)


@mcp.tool()
def hibob_get_today_out() -> str:
    """Get who is out of office today. Use for quick "who's out?" questions without specific dates."""
    from datetime import date as date_type
    today = date_type.today().isoformat()
    try:
        result = _hibob_api_call("timeoff/outtoday", method="GET", params={
            "today": today, "includeHourly": "true",
        })
    except Exception as e:
        return f"Error fetching today's absences: {e}"

    outs = result.get("outs", []) if isinstance(result, dict) else (result if isinstance(result, list) else [])
    if not outs:
        return f"No one is out today ({today})."

    lines = [f"Out today ({today}): {len(outs)} people\n"]
    for entry in outs:
        line = _format_today_entry(entry)
        if line:
            lines.append(line)
    return "\n".join(lines)


@mcp.tool()
def hibob_submit_timeoff_request(employee_id: str, policy_type: str, start_date: str, end_date: str, reason: str = "") -> str:
    """Submit a time-off request for an employee.

    Parameters:
        employee_id (str): The HiBob employee ID.
        policy_type (str): The policy type name (e.g. "Holiday", "Sick Leave").
        start_date (str): Start date in YYYY-MM-DD format.
        end_date (str): End date in YYYY-MM-DD format.
        reason (str, optional): Reason for the request.
    """
    body = {
        "policyType": policy_type,
        "startDate": start_date,
        "endDate": end_date,
        "requestRangeType": "days",
        "startDatePortion": "all_day",
        "endDatePortion": "all_day",
    }
    if reason:
        body["reason"] = reason

    try:
        result = _hibob_api_call(f"timeoff/employees/{employee_id}/requests", body=body, method="POST")
        return f"Time-off request submitted successfully. {str(result) if result else ''}"
    except Exception as e:
        return f"Error submitting time-off request: {e}"


@mcp.tool()
def hibob_get_employee_tasks(employee_id: str) -> str:
    """Get tasks for a specific employee.

    Parameters:
        employee_id (str): The HiBob employee ID.
    """
    try:
        result = _hibob_api_call(f"tasks/people/{employee_id}", method="GET")
    except Exception as e:
        return f"Error fetching tasks: {e}"

    tasks = result if isinstance(result, list) else result.get("tasks", [])
    if not tasks:
        return "No tasks found for this employee."

    lines = [f"Tasks ({len(tasks)}):\n"]
    for task in tasks:
        if not isinstance(task, dict):
            continue
        title = task.get("title", task.get("name", "Untitled"))
        status = task.get("status", "")
        due = task.get("dueDate", task.get("date", ""))
        desc = task.get("description", "")
        parts = [f"- {title}"]
        if status:
            parts[0] += f" [{status}]"
        if due:
            parts[0] += f" (due: {due})"
        if desc:
            parts.append(f"  {desc[:200]}")
        lines.append("\n".join(parts))
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
