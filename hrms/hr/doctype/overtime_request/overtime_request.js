// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

function calculateOvertimeHours(frm, fromDatetime, tillDatetime, is_holiday) {
	if (fromDatetime && tillDatetime) {
		const fromDate = frappe.datetime.str_to_obj(fromDatetime);
		const tillDate = frappe.datetime.str_to_obj(tillDatetime);

		const diffMs = tillDate - fromDate;
		if (diffMs <= 0) {
			frm.set_value("overtime_hours", 0);
			return;
		}

		let diffHours = diffMs / (1000 * 60 * 60);
		if (is_holiday) diffHours *= 2;

		frm.set_value("overtime_hours", parseFloat(diffHours.toFixed(2)));
	} else {
		frm.set_value("overtime_hours", 0);
	}
}

function isRequestDateValid(frm) {
	const requestDate = frappe.datetime.str_to_obj(frm.doc.request_date);
	const creationDate = frappe.datetime.str_to_obj(frm.doc.posting_date);
	if (requestDate < creationDate) {
		frappe.msgprint(__("Request Date cannot be before the creation date."));
		frm.set_value("request_date", null);
	}
}

async function validateHolidayDate(frm) {
	if (!frm.doc.employee || !frm.doc.request_date) return;

	try {
		const employee = await frappe.db.get_doc("Employee", frm.doc.employee);
		if (!employee.default_shift) {
			frappe.msgprint(__("This employee has no default shift assigned."));
			frm.set_value("is_holiday", 0);
			return;
		}

		const shift = await frappe.db.get_doc("Shift Type", employee.default_shift);
		if (!shift.holiday_list) {
			frappe.msgprint(__("No holiday list is linked to the employee's shift type."));
			frm.set_value("is_holiday", 0);
			return;
		}

		const holiday_list = await frappe.db.get_doc("Holiday List", shift.holiday_list);
		const isDateHoliday = holiday_list.holidays.some(
			(holiday) => holiday.holiday_date === frm.doc.request_date
		);

		if (isDateHoliday && !frm.doc.is_holiday) {
			frm.set_value("is_holiday", 1);
			frappe.show_alert({
				message: __('Date is a holiday — "Is Holiday" auto-checked.'),
				indicator: "green",
			});
		} else if (!isDateHoliday && frm.doc.is_holiday) {
			frm.set_value("is_holiday", 0);
			frappe.show_alert({
				message: __('Date is not a holiday — "Is Holiday" unchecked.'),
				indicator: "orange",
			});
		}

		frm.set_df_property("from_time", "read_only", 0);
		frm.set_df_property("to_time", "read_only", 0);
	} catch (err) {
		const message = err?.message || err?.exc || "Unexpected error during holiday validation.";
		frappe.msgprint(__(message));
	}
}

frappe.ui.form.on("Overtime Request", {
	from_time(frm) {
		calculateOvertimeHours(frm, frm.doc.from_time, frm.doc.to_time, frm.doc.is_holiday);
	},
	to_time(frm) {
		calculateOvertimeHours(frm, frm.doc.from_time, frm.doc.to_time, frm.doc.is_holiday);
	},
	is_holiday(frm) {
		validateHolidayDate(frm);
		calculateOvertimeHours(frm, frm.doc.from_time, frm.doc.to_time, frm.doc.is_holiday);
	},
	request_date(frm) {
		validateHolidayDate(frm);
	},
	before_save(frm) {
		isRequestDateValid(frm);
		validateHolidayDate(frm);
	},
});
