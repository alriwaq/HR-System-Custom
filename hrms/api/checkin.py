import frappe
from frappe.utils import get_datetime, getdate, timedelta


@frappe.whitelist(allow_guest=False)
def bulk_upload_checkins():
	"""Receive checkin records from an attendance device, create Employee Checkin docs, and assign IN/OUT log types."""
	data = frappe.request.get_json() or {}

	records = (
		data.get("records")
		or data.get("checkins")
		or data.get("records[]")
		or data.get("checkin_records")
	)

	if not records:
		frappe.response["message"] = {
			"success": False,
			"error": "No records received",
			"total_records": 0,
		}
		return

	try:
		parsed_records = _parse_and_validate_records(records)
		success_count, failed_count, failed_records = _create_checkin_documents(parsed_records)

		if success_count > 0:
			log_type_summary = _process_log_types()
		else:
			log_type_summary = _empty_log_summary()

		frappe.response["message"] = _build_response(
			total_records=len(parsed_records),
			success_count=success_count,
			failed_count=failed_count,
			failed_records=failed_records,
			log_type_summary=log_type_summary,
		)

	except Exception as e:
		frappe.log_error("Batch Upload Error", frappe.get_traceback())
		frappe.response["message"] = {
			"success": False,
			"error": str(e),
			"message": "Server script failed",
		}


# ── helpers ───────────────────────────────────────────────────────────────────


def _parse_and_validate_records(records):
	if isinstance(records, str):
		records = records.strip()
		if not records:
			frappe.throw("Records parameter is empty")
		try:
			records = frappe.parse_json(records)
		except Exception as e:
			frappe.throw(f"Invalid JSON: {str(e)}")

	if not isinstance(records, list):
		frappe.throw("Records must be a list")

	return records


_employee_cache: dict = {}


def _resolve_employee(attendance_device_id: str) -> str:
	"""Return Employee name for the given attendance_device_id (cached per request)."""
	if attendance_device_id in _employee_cache:
		return _employee_cache[attendance_device_id]

	employee_name = frappe.db.get_value(
		"Employee", {"attendance_device_id": attendance_device_id}, "name"
	)
	if not employee_name:
		raise ValueError(f"No Employee found for attendance_device_id: {attendance_device_id}")

	_employee_cache[attendance_device_id] = employee_name
	return employee_name


def _create_checkin_documents(records):
	frappe.flags.in_import = True
	success_count = 0
	failed_count = 0
	failed_records = []
	employee_cache: dict = {}

	for idx, record in enumerate(records):
		try:
			employee_field_value = str(record.get("employee_field_value") or "").strip()
			if not employee_field_value:
				raise ValueError(f"Missing employee_field_value in record {idx}")

			timestamp_str = str(record.get("timestamp") or "").strip()
			if not timestamp_str:
				raise ValueError(f"Missing timestamp in record {idx}")

			device_id = record.get("device_id")

			if employee_field_value not in employee_cache:
				employee_cache[employee_field_value] = frappe.db.get_value(
					"Employee", {"attendance_device_id": employee_field_value}, "name"
				)
				if not employee_cache[employee_field_value]:
					raise ValueError(
						f"No Employee found for attendance_device_id: {employee_field_value}"
					)
			employee_name = employee_cache[employee_field_value]

			timestamp = get_datetime(timestamp_str)

			checkin = frappe.get_doc(
				{
					"doctype": "Employee Checkin",
					"employee": employee_name,
					"time": timestamp,
					"device_id": device_id,
					"log_type": None,
				}
			)
			checkin.insert(ignore_permissions=True)
			success_count += 1

		except Exception as e:
			failed_count += 1
			failed_records.append(
				{
					"index": idx,
					"employee_field_value": record.get("employee_field_value"),
					"timestamp": record.get("timestamp"),
					"device_id": record.get("device_id"),
					"error": str(e),
				}
			)
			frappe.log_error(f"Checkin record {idx} failed", str(e))

	frappe.db.commit()
	frappe.flags.in_import = False
	return success_count, failed_count, failed_records


def _process_log_types() -> dict:
	try:
		check_ins = frappe.get_all(
			"Employee Checkin",
			filters={"log_type": ["in", (None, "")]},
			fields=["name", "employee", "time"],
			order_by="employee, time",
		)
		if not check_ins:
			return _empty_log_summary()

		employee_logs = _group_by_employee_and_date(check_ins)
		return _assign_log_types(employee_logs)

	except Exception as e:
		frappe.log_error("Log Type Processing Error", frappe.get_traceback())
		return {"error": str(e)}


def _group_by_employee_and_date(check_ins: list) -> dict:
	logs: dict = {}
	for entry in check_ins:
		time = get_datetime(entry["time"])
		date_str = getdate(time)
		logs.setdefault(entry["employee"], {}).setdefault(date_str, []).append(
			{"name": entry["name"], "time": time}
		)
	return logs


def _assign_log_types(employee_logs: dict) -> dict:
	processed_employees = 0
	marked_in = 0
	marked_out = 0
	deleted_duplicates = 0

	for emp_id, dates in employee_logs.items():
		processed_employees += 1
		for date, logs in dates.items():
			logs.sort(key=lambda x: x["time"])
			filtered_logs, deleted = _remove_duplicates(logs)
			deleted_duplicates += deleted

			if filtered_logs:
				frappe.db.set_value("Employee Checkin", filtered_logs[0]["name"], "log_type", "IN")
				marked_in += 1
				if len(filtered_logs) > 1:
					frappe.db.set_value(
						"Employee Checkin", filtered_logs[-1]["name"], "log_type", "OUT"
					)
					marked_out += 1

	frappe.db.commit()
	return {
		"processed_employees": processed_employees,
		"marked_in": marked_in,
		"marked_out": marked_out,
		"deleted_duplicates": deleted_duplicates,
	}


def _remove_duplicates(logs: list) -> tuple[list, int]:
	"""Drop checkins within 5 minutes of the previous one (keep first)."""
	filtered = []
	prev_time = None
	deleted = 0

	for log in logs:
		if prev_time and (log["time"] - prev_time).total_seconds() <= 300:
			try:
				frappe.delete_doc("Employee Checkin", log["name"], ignore_permissions=True)
				deleted += 1
			except Exception:
				pass
		else:
			filtered.append(log)
			prev_time = log["time"]

	return filtered, deleted


def _empty_log_summary() -> dict:
	return {
		"processed_employees": 0,
		"marked_in": 0,
		"marked_out": 0,
		"deleted_duplicates": 0,
	}


def _build_response(total_records, success_count, failed_count, failed_records, log_type_summary) -> dict:
	if failed_count == 0:
		msg = f"All {success_count} records uploaded successfully."
	elif success_count == 0:
		msg = f"All {failed_count} records failed."
	else:
		msg = f"{success_count}/{total_records} records uploaded, {failed_count} failed."

	return {
		"success": True,
		"total_records": total_records,
		"success_count": success_count,
		"failed_count": failed_count,
		"failed_records": failed_records,
		"log_type_summary": log_type_summary,
		"message": msg,
	}
