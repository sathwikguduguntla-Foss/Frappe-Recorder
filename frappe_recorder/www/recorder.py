import frappe

no_cache = 1


def get_context(context):
	context.boot = {
		"csrf_token": frappe.sessions.get_csrf_token(),
		"site_name": frappe.local.site,
		"recorder_user": frappe.session.user,
	}
	return context
