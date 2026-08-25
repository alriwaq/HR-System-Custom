# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class OvertimeRequest(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amended_from: DF.Link | None
		custom_missions_hours: DF.Float
		custom_total_mission_hours: DF.Float
		employee: DF.Link
		end_time: DF.Time | None
		from_time: DF.Datetime | None
		is_holiday: DF.Check
		overtime_approver: DF.Link | None
		overtime_hours: DF.Float
		overtime_reason: DF.SmallText | None
		overtime_type: DF.Literal["", "سهرة", "سهرة صبة", "مأمورية"]
		posting_date: DF.Datetime
		real_spent_overtime_hours: DF.Float
		request_date: DF.Date
		shift: DF.Link | None
		start_time: DF.Time | None
		target_hours: DF.Float
		to_time: DF.Datetime | None
		validated_by_attendance: DF.Check

	# end: auto-generated types

	pass
