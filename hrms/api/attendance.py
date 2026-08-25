import frappe
from frappe.utils import add_to_date, cint, get_time, get_weekday, getdate, time_diff_in_hours, to_timedelta


@frappe.whitelist()
def mark_incentives_deductions_absences(from_date=None, to_date=None, skip_existing=1):
	"""Process attendance records in the date range and create Incentive And Deductions docs."""
	from_date = getdate(from_date)
	to_date = getdate(to_date)
	skip_existing = cint(skip_existing)

	existing_records: set = set()
	if skip_existing:
		for rec in frappe.get_all(
			"Incentive And Deductions",
			filters={"attendance_date": ["between", [from_date, to_date]]},
			fields=["employee", "attendance_record"],
		):
			existing_records.add((rec.employee, rec.attendance_record))

	recs = frappe.get_all(
		"Attendance",
		{"docstatus": 1, "attendance_date": ["between", [from_date, to_date]]},
		["name", "employee", "attendance_date", "employee_name", "shift",
		 "in_time", "out_time", "working_hours", "status"],
	)

	emp_attendance: dict = {}
	for doc in recs:
		emp_attendance.setdefault(doc.employee, []).append(doc)

	count = 0
	for employee, docs in emp_attendance.items():
		present_docs = [d for d in docs if d.status == "Present"]
		absent_docs = [d for d in docs if d.status == "Absent"]

		count += _process_absent_streaks(employee, absent_docs, existing_records, skip_existing)
		for doc in present_docs:
			count += _process_present_day(doc, existing_records, skip_existing)

	frappe.response["message"] = f"{count} record(s) created between {from_date} and {to_date}."


# ── helpers ───────────────────────────────────────────────────────────────────


def _to_seconds(tstr):
	td = to_timedelta(tstr) if tstr else None
	return td.total_seconds() if td else None


def _get_shift_day_times(shift_doc, attendance_date):
	"""Return (start, end) from the shift's custom weekday config for the given date."""
	day_name = get_weekday(getdate(attendance_date))
	for row in shift_doc.custom_shift_weekdays:
		if row.weekdays == day_name:
			return row.start or None, row.end or None
	return None, None


def _validate_overtime_request(
	employee, attendance_date, att_in_sec, start_sec, att_out_sec, end_sec,
	overtime_candidate, working_hours=None, shift_start=None, shift_end=None
):
	"""
	Update Overtime Request docs with real validated hours.
	Returns (mission_realtime_hours, is_holiday).
	"""
	overtime_requests = frappe.get_all(
		"Overtime Request",
		filters={"employee": employee, "request_date": attendance_date, "docstatus": 1},
		fields=["name", "from_time", "to_time", "validated_by_attendance", "is_holiday", "overtime_type"],
	)

	# 1. Holiday: double working hours and skip all other OT logic
	for req in overtime_requests:
		if req.is_holiday:
			double_hours = (working_hours or 0) * 2
			frappe.db.set_value(
				"Overtime Request", req.name,
				{"real_spent_overtime_hours": double_hours, "validated_by_attendance": 1},
			)
			return double_hours, True

	realtime = 0.0

	# 2. Mission (مأمورية): hours the employee was outside the workplace during shift
	for req in overtime_requests:
		if req.overtime_type != "مأمورية":
			continue

		# Pre-compute once to avoid NameError if either conditional block is skipped
		req_from_sec = _to_seconds(to_timedelta(get_time(req.from_time))) if req.from_time else None
		req_to_sec = _to_seconds(to_timedelta(get_time(req.to_time))) if req.to_time else None

		before_overlap = 0.0
		if att_in_sec is not None and req_from_sec is not None and req_to_sec is not None:
			if req_to_sec <= att_in_sec:
				before_overlap = (req_to_sec - req_from_sec) / 3600.0
			elif req_from_sec < att_in_sec:
				before_overlap = (att_in_sec - req_from_sec) / 3600.0

		after_overlap = 0.0
		if att_out_sec is not None and req_from_sec is not None and req_to_sec is not None:
			if req_from_sec >= att_out_sec:
				after_overlap = (req_to_sec - req_from_sec) / 3600.0
			elif req_to_sec > att_out_sec:
				after_overlap = (req_to_sec - att_out_sec) / 3600.0

		real_ot = before_overlap + after_overlap
		if real_ot > 0:
			add_hours = min(real_ot, overtime_candidate - realtime)
			realtime += add_hours
			frappe.db.set_value(
				"Overtime Request", req.name,
				{
					"custom_missions_hours": real_ot,
					"custom_total_mission_hours": real_ot + add_hours,
					"validated_by_attendance": 1,
				},
			)
			if realtime >= overtime_candidate:
				break

	# 3. Regular overtime: early-in / late-out overlapping the request window
	target_hours = time_diff_in_hours(shift_end, shift_start) if shift_start and shift_end else 0
	real_spent_overtime_hours = 0.0

	for req in overtime_requests:
		req_from = to_timedelta(get_time(req.from_time)) if req.from_time else None
		req_to = to_timedelta(get_time(req.to_time)) if req.to_time else None

		before_overlap = 0.0
		if att_in_sec is not None and start_sec is not None and req_to and att_in_sec < start_sec:
			overlap_start = max(att_in_sec, _to_seconds(req_from)) if req_from else att_in_sec
			overlap_end = min(start_sec, _to_seconds(req_to))
			if overlap_end > overlap_start:
				before_overlap = (overlap_end - overlap_start) / 3600.0

		after_overlap = 0.0
		if att_out_sec is not None and end_sec is not None and req_from and att_out_sec > end_sec:
			overlap_start = max(end_sec, _to_seconds(req_from))
			overlap_end = min(att_out_sec, _to_seconds(req_to)) if req_to else att_out_sec
			if overlap_end > overlap_start:
				after_overlap = (overlap_end - overlap_start) / 3600.0

		req_real_overtime = before_overlap + after_overlap
		if req_real_overtime > 0:
			add_hours = min(req_real_overtime, overtime_candidate - real_spent_overtime_hours)
			real_spent_overtime_hours += add_hours
			frappe.db.set_value(
				"Overtime Request", req.name,
				{
					"target_hours": target_hours,
					"real_spent_overtime_hours": add_hours,
					"validated_by_attendance": 1,
				},
			)
			if real_spent_overtime_hours >= overtime_candidate:
				break

	return realtime, False


def _process_absent_streaks(employee, absent_docs, existing_records, skip_existing):
	if not absent_docs:
		return 0

	absent_docs_sorted = sorted(absent_docs, key=lambda d: d.attendance_date)
	streaks = []
	streak = []
	for doc in absent_docs_sorted:
		if not streak:
			streak = [doc]
		else:
			prev_date = getdate(streak[-1].attendance_date)
			curr_date = getdate(doc.attendance_date)
			if curr_date == add_to_date(prev_date, days=1):
				streak.append(doc)
			else:
				streaks.append(streak)
				streak = [doc]
	if streak:
		streaks.append(streak)

	count = 0
	for streak in streaks:
		attendance_names = [d.name for d in streak]
		if skip_existing and frappe.get_all(
			"Incentive And Deductions",
			filters={"employee": employee, "attendance_record": ["in", attendance_names]},
		):
			continue

		first_doc = streak[0]
		if not first_doc.shift:
			continue

		shift_doc = frappe.get_doc("Shift Type", first_doc.shift)
		start, end = _get_shift_day_times(shift_doc, first_doc.attendance_date)

		total_ratio = 0.0
		absent_days_streak = []
		for idx, doc in enumerate(streak):
			# Ratios: 1.25, 1.50, 1.75, then 2.0 for all subsequent days
			ratio = min(1.25 + idx * 0.25, 2.0)
			total_ratio += ratio
			absent_days_streak.append({
				"attendance_record": doc.name,
				"absent_date": doc.attendance_date,
				"absent_day_ratio": ratio,
			})

		nd = frappe.new_doc("Incentive And Deductions")
		nd.update({
			"employee": employee,
			"attendance_record": attendance_names[-1],
			"attendance_date": streak[-1].attendance_date,
			"employee_name": streak[0].employee_name,
			"type": "Absent",
			"expected_hours": time_diff_in_hours(end, start) if start and end else 0,
			"shift": first_doc.shift,
			"shift_start_time": start,
			"shift_end_time": end,
			"absent_days_streak": absent_days_streak,
			"total_absent_days_ratio": total_ratio,
			"notes": f"Auto-calculated Absent Streak ({len(streak)} days)",
		})
		nd.insert(ignore_permissions=True)
		count += 1

	return count


def _process_present_day(doc, existing_records, skip_existing):
	if not doc.shift:
		return 0

	shift_doc = frappe.get_doc("Shift Type", doc.shift)
	start, end = _get_shift_day_times(shift_doc, doc.attendance_date)

	att_in = to_timedelta(get_time(doc.in_time)) if doc.in_time else None
	att_out = to_timedelta(get_time(doc.out_time)) if doc.out_time else None

	start_sec = _to_seconds(start)
	end_sec = _to_seconds(end)
	att_in_sec = _to_seconds(att_in)
	att_out_sec = _to_seconds(att_out)

	max_incentive_hours = shift_doc.custom_maximum_overtime_hours or 0

	incentive_before = 0.0
	incentive_after = 0.0
	if att_in_sec is not None and start_sec is not None and att_in_sec < start_sec:
		incentive_before = time_diff_in_hours(start, att_in)
	if att_out_sec is not None and end_sec is not None and att_out_sec > end_sec:
		incentive_after = time_diff_in_hours(att_out, end)
	total_incentive = incentive_before + incentive_after

	if total_incentive > max_incentive_hours:
		incentive = max_incentive_hours
		overtime_candidate = total_incentive - max_incentive_hours
	else:
		incentive = total_incentive
		overtime_candidate = 0.0

	deduction = 0.0
	if att_in_sec is not None and start_sec is not None and att_in_sec > start_sec:
		deduction += time_diff_in_hours(att_in, start)
	if att_out_sec is not None and end_sec is not None and att_out_sec < end_sec:
		deduction += time_diff_in_hours(end, att_out)

	# Always run — updates Overtime Request docs as a side effect regardless of skip_existing
	_, is_holiday = _validate_overtime_request(
		doc.employee, doc.attendance_date,
		att_in_sec, start_sec, att_out_sec, end_sec,
		overtime_candidate, doc.working_hours,
		shift_start=start, shift_end=end,
	)

	if is_holiday:
		return 0

	if skip_existing and (doc.employee, doc.name) in existing_records:
		return 0

	if not att_in or not att_out:
		nd = frappe.new_doc("Incentive And Deductions")
		nd.update({
			"employee": doc.employee,
			"attendance_record": doc.name,
			"attendance_date": doc.attendance_date,
			"employee_name": doc.employee_name,
			"shift": doc.shift,
			"shift_start_time": start,
			"shift_end_time": end,
			"check_in": att_in if att_in else "",
			"check_out": att_out if att_out else "",
			"type": "Missed Punch",
			"missed_punch_days_deduction": 0.5,
			"notes": "Auto-calculated Missed Punch",
		})
		nd.insert(ignore_permissions=True)
		return 1

	if incentive or deduction:
		nd = frappe.new_doc("Incentive And Deductions")
		nd.update({
			"employee": doc.employee,
			"attendance_record": doc.name,
			"attendance_date": doc.attendance_date,
			"employee_name": doc.employee_name,
			"shift": doc.shift,
			"shift_start_time": start,
			"shift_end_time": end,
			"check_in": att_in,
			"check_out": att_out,
			"incentive_hours": incentive,
			"deduction_hours": deduction,
			"total_working_hours": doc.working_hours,
			"expected_hours": time_diff_in_hours(end, start) if start and end else 0,
			"type": "Incentive/Deduction",
			"notes": "Auto-calculated Incentive/Deduction",
		})
		nd.insert(ignore_permissions=True)
		return 1

	return 0
