import frappe


def calculate_overtime_and_incentives(doc, method=None):
	"""Populate overtime and incentive child tables on the Salary Slip before save."""
	doc.custom_overtime_requests = []
	doc.custom_incentives_and_deductions = []

	if not (doc.employee and doc.start_date and doc.end_date):
		return

	_fill_overtime_requests(doc)
	_fill_incentives_and_deductions(doc)


def _fill_overtime_requests(doc):
	total_overtime_normal_hours = 0.0
	total_overtime_hours = 0.0
	total_mission_hours = 0.0

	overtime_requests = frappe.get_all(
		"Overtime Request",
		filters={
			"employee": doc.employee,
			"request_date": ["between", [doc.start_date, doc.end_date]],
			"docstatus": 1,
		},
		fields=[
			"name",
			"overtime_hours",
			"overtime_type",
			"real_spent_overtime_hours",
			"validated_by_attendance",
			"custom_total_mission_hours",
		],
	)

	for ot in overtime_requests:
		doc.append(
			"custom_overtime_requests",
			{
				"type": ot.overtime_type,
				"overtime_request": ot.name,
				"overtime_hours": ot.overtime_hours,
				"real_spent_overtime_hours": ot.real_spent_overtime_hours,
				"validated_mission_hour": ot.custom_total_mission_hours,
			},
		)

		if ot.validated_by_attendance == 1 or ot.overtime_type == "مأمورية":
			if ot.overtime_type == "سهرة":
				total_overtime_normal_hours += ot.real_spent_overtime_hours or 0
			elif ot.overtime_type == "سهرة صبة":
				total_overtime_hours += ot.real_spent_overtime_hours or 0
			elif ot.overtime_type == "مأمورية":
				total_mission_hours += float(ot.custom_total_mission_hours or 0)

	doc.custom_total_overtime_normal_hours = total_overtime_normal_hours
	doc.custom_total_overtime_hours_sabba = total_overtime_hours
	doc.custom_mission_hours = total_mission_hours


def _fill_incentives_and_deductions(doc):
	total_incentive_minutes = 0.0
	total_deduction_minutes = 0.0
	total_deducted_days = 0.0

	incentive_records = frappe.get_all(
		"Incentive And Deductions",
		filters={
			"employee": doc.employee,
			"attendance_date": ["between", [doc.start_date, doc.end_date]],
			"docstatus": 1,
		},
		fields=[
			"type",
			"name",
			"incentive_hours",
			"deduction_hours",
			"missed_punch_days_deduction",
			"total_absent_days_ratio",
		],
	)

	for rec in incentive_records:
		incentive_minutes = round((rec.incentive_hours or 0) * 60, 2)
		deduction_minutes = round((rec.deduction_hours or 0) * 60, 2)

		doc.append(
			"custom_incentives_and_deductions",
			{
				"type": rec.type,
				"incentive_deduction_record": rec.name,
				"incentive_minutes": incentive_minutes,
				"deduction_minutes": deduction_minutes,
				"missed_punch_days_deduction": rec.missed_punch_days_deduction,
				"total_absent_days_ratio": rec.total_absent_days_ratio,
			},
		)

		total_incentive_minutes += incentive_minutes
		total_deduction_minutes += deduction_minutes
		total_deducted_days += float(rec.missed_punch_days_deduction or 0) + float(
			rec.total_absent_days_ratio or 0
		)

	doc.custom_total_incentives_hours = round(total_incentive_minutes / 60, 2)
	doc.custom_total_dedutions_hours = round(total_deduction_minutes / 60, 2)
	doc.custom_total_deduction_days = total_deducted_days

	doc.custom_total_incentives = _minutes_to_time(total_incentive_minutes)
	doc.custom_total_dedutions = _minutes_to_time(total_deduction_minutes)


def _minutes_to_time(minutes):
	hrs = int(minutes // 60)
	mins = int(minutes % 60)
	return f"{hrs:02d}:{mins:02d}"
