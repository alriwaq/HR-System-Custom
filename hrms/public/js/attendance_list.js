frappe.listview_settings["Attendance"] = frappe.listview_settings["Attendance"] || {};
frappe.listview_settings["Attendance"].onload = function (listview) {
	if (listview.custom_button_added) return;
	listview.custom_button_added = true;

	listview.page.add_inner_button(__("Calculate Incentives and Deductions"), function () {
		const dialog = new frappe.ui.Dialog({
			title: __("Select Date Range"),
			fields: [
				{ label: __("From Date"), fieldname: "from_date", fieldtype: "Date", reqd: 1 },
				{ label: __("To Date"), fieldname: "to_date", fieldtype: "Date", reqd: 1 },
				{
					label: __("Skip Already Calculated Records"),
					fieldname: "skip_existing",
					fieldtype: "Check",
					default: 1,
				},
			],
			primary_action_label: __("Submit"),
			primary_action(values) {
				if (values.from_date > values.to_date) {
					frappe.msgprint(__("From Date cannot be after To Date."));
					return;
				}

				dialog.hide();

				frappe.call({
					method: "hrms.api.attendance.mark_incentives_deductions_absences",
					args: {
						from_date: values.from_date,
						to_date: values.to_date,
						skip_existing: values.skip_existing,
					},
					callback(r) {
						if (r && r.message) {
							frappe.msgprint(r.message);
							listview.refresh();
						} else {
							frappe.msgprint(__("No response from server."));
						}
					},
				});
			},
		});

		dialog.show();
	});
};
