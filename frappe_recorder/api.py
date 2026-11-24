# Copyright (c) 2026, Sathwik Guduguntla  and contributors
# For license information, please see license.txt

"""HTTP API used by the recorder frontend.

Recording flow:
  1. create_recording   -> reserves a share token, so the link exists before upload ends
  2. upload_chunk       -> called repeatedly while recording; appends to the video file
  3. finalize_recording -> marks the recording Ready and adds the video to the File Manager

Anyone holding the share link (/r/<token>) can watch through get_recording + stream,
as long as link sharing is on for that recording.
"""

import base64
import os
import re

import frappe
from frappe import _
from frappe.utils import cint, get_url
from werkzeug.utils import send_file

from frappe_recorder.frappe_recorder.doctype.screen_recording.screen_recording import (
	recording_file_path,
	thumbnail_dir,
	video_file_name,
)

DOCTYPE = "Screen Recording"

# Container formats MediaRecorder can produce, mapped to a file extension.
MIME_EXTENSIONS = {
	"video/webm": "webm",
	"video/mp4": "mp4",
	"video/x-matroska": "mkv",
}
MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024


# ---------------------------------------------------------------- helpers


def _require_login():
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in to use the recorder."), frappe.AuthenticationError)


def _is_manager() -> bool:
	return "System Manager" in frappe.get_roles()


def _get_doc(token: str, for_update: bool = False):
	name = frappe.db.get_value(DOCTYPE, {"token": token}) if token else None
	if not name:
		frappe.throw(_("This recording does not exist or was deleted."), frappe.DoesNotExistError)
	return frappe.get_doc(DOCTYPE, name, for_update=for_update)


def _is_owner(doc) -> bool:
	user = frappe.session.user
	return user != "Guest" and (doc.owner == user or _is_manager())


def _get_owned_doc(token: str, for_update: bool = False):
	_require_login()
	doc = _get_doc(token, for_update=for_update)
	if not _is_owner(doc):
		frappe.throw(_("You do not have access to this recording."), frappe.PermissionError)
	return doc


def _get_viewable_doc(token: str):
	doc = _get_doc(token)
	if not doc.is_public and not _is_owner(doc):
		frappe.throw(_("This recording is private."), frappe.PermissionError)
	return doc


def share_url(token: str) -> str:
	return get_url(f"/r/{token}")


def _serialize(doc, is_owner: bool) -> dict:
	data = {
		"token": doc.token,
		"title": doc.title,
		"status": doc.status,
		"duration_seconds": doc.duration_seconds or 0,
		"view_count": doc.view_count or 0,
		"thumbnail": doc.thumbnail,
		"creation": doc.creation,
		"share_url": share_url(doc.token),
		"stream_url": f"/api/method/frappe_recorder.api.stream?token={doc.token}",
		"mime_type": doc.mime_type,
		"is_owner": is_owner,
		"transcript_status": doc.transcript_status or "Not Started",
		"insights_status": doc.insights_status or "Not Started",
		"sop_status": doc.sop_status or "Not Started",
	}
	if is_owner:
		data.update(
			{
				"is_public": cint(doc.is_public),
				"file_size": doc.file_size or 0,
			}
		)
	return data


# ---------------------------------------------------------------- session


@frappe.whitelist(allow_guest=True)
def get_session():
	"""Who is using the app, and what they are allowed to do."""
	user = frappe.session.user
	if user == "Guest":
		return {"user": None, "is_manager": False}
	return {
		"user": user,
		"full_name": frappe.utils.get_fullname(user),
		"is_manager": _is_manager(),
	}


# ---------------------------------------------------------------- recording


@frappe.whitelist(methods=["POST"])
def create_recording(title: str | None = None, mime_type: str = "video/webm"):
	_require_login()

	base_mime = (mime_type or "").split(";")[0].strip().lower()
	if base_mime not in MIME_EXTENSIONS:
		frappe.throw(_("Unsupported video format: {0}").format(mime_type))

	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"title": (title or "").strip() or _default_title(),
			"status": "Recording",
			"is_public": 1,
			"mime_type": base_mime,
		}
	)
	doc.insert(ignore_permissions=True)
	doc.db_set("video_file", video_file_name(doc.token, MIME_EXTENSIONS[base_mime]), update_modified=False)
	return {"token": doc.token, "share_url": share_url(doc.token)}


def _default_title() -> str:
	return _("Recording - {0}").format(
		frappe.utils.format_datetime(frappe.utils.now_datetime(), "d MMM yyyy, h:mm a")
	)


@frappe.whitelist(methods=["POST"])
def upload_chunk(token: str, index: int):
	"""Append one piece of the video. Chunks must arrive in order; a repeated
	chunk (client retry after a dropped response) is acknowledged and ignored."""
	# The row lock makes a retry wait for the request it is retrying, so it then
	# sees that chunk as received instead of appending it a second time.
	doc = _get_owned_doc(token, for_update=True)
	if doc.status != "Recording":
		frappe.throw(_("This recording is already finished."))

	index = cint(index)
	received = cint(doc.chunks_received)
	if index < received:
		return {"received": received}
	if index > received:
		frappe.throw(_("Chunk {0} arrived before chunk {1}.").format(index, received))

	chunk = frappe.request.files.get("chunk")
	if not chunk:
		frappe.throw(_("No video data received."))

	path = doc.local_video_path()
	if not path:
		frappe.throw(_("The video file is missing."), frappe.DoesNotExistError)
	offset = cint(doc.bytes_received)
	if received and not offset:
		# Recording started before bytes_received was tracked.
		offset = os.path.getsize(path)

	# local_video_path confines the file to the site's private files directory.
	with open(path, "ab") as f:  # nosemgrep: frappe-security-file-traversal
		# Drop bytes left behind by a request that died before it was committed.
		f.truncate(offset)
		while True:
			data = chunk.stream.read(1024 * 1024)
			if not data:
				break
			f.write(data)
			offset += len(data)

	doc.db_set({"chunks_received": received + 1, "bytes_received": offset}, update_modified=False)
	return {"received": received + 1}


@frappe.whitelist(methods=["POST"])
def finalize_recording(token: str, duration_seconds: int = 0, thumbnail: str | None = None):
	doc = _get_owned_doc(token)
	if doc.status == "Recording":
		if not doc.has_local_video():
			frappe.throw(_("Nothing was recorded."))

		doc.duration_seconds = cint(duration_seconds)
		doc.file_size = os.path.getsize(doc.local_video_path())
		doc.status = "Ready"
		if thumbnail:
			doc.thumbnail = _save_thumbnail(doc.token, thumbnail)
		doc.try_add_to_file_manager()
		doc.save(ignore_permissions=True)

	return _serialize(doc, is_owner=True)


def _save_thumbnail(token: str, data_url: str) -> str | None:
	match = re.match(r"^data:image/jpeg;base64,([A-Za-z0-9+/=]+)$", data_url or "")
	if not match:
		return None
	content = base64.b64decode(match.group(1))
	if len(content) > MAX_THUMBNAIL_BYTES:
		return None
	path = recording_file_path(thumbnail_dir(), f"{token}.jpg")
	# recording_file_path checks the filename and rejects symlink redirects.
	with open(path, "wb") as f:  # nosemgrep: frappe-security-file-traversal
		f.write(content)
	return f"/files/recorder/{token}.jpg"


@frappe.whitelist(methods=["POST"])
def update_recording(token: str, title: str | None = None, is_public: int | None = None):
	doc = _get_owned_doc(token)
	if title is not None:
		title = title.strip()
		if not title:
			frappe.throw(_("Title cannot be empty."))
		doc.title = title[:140]
	if is_public is not None:
		doc.is_public = cint(is_public)
	doc.save(ignore_permissions=True)
	return _serialize(doc, is_owner=True)


@frappe.whitelist(methods=["POST"])
def delete_recording(token: str):
	"""Removes the recording and its video, including the File Manager entry."""
	doc = _get_owned_doc(token)
	frappe.delete_doc(DOCTYPE, doc.name, ignore_permissions=True)
	return {"deleted": token}


@frappe.whitelist()
def list_recordings(search: str | None = None, start: int = 0, limit: int = 60):
	_require_login()
	filters = {"owner": frappe.session.user, "status": ["!=", "Recording"]}
	if search:
		filters["title"] = ["like", f"%{search}%"]
	names = frappe.get_all(
		DOCTYPE,
		filters=filters,
		order_by="creation desc",
		limit_start=cint(start),
		limit_page_length=min(cint(limit) or 60, 200),
		pluck="name",
	)
	return [_serialize(frappe.get_doc(DOCTYPE, name), is_owner=True) for name in names]


# ---------------------------------------------------------------- viewing


@frappe.whitelist(allow_guest=True)
def get_recording(token: str):
	doc = _get_viewable_doc(token)
	return _serialize(doc, is_owner=_is_owner(doc))


@frappe.whitelist(allow_guest=True, methods=["POST"])
def register_view(token: str):
	"""Counts one view. The owner watching their own video does not count."""
	doc = _get_viewable_doc(token)
	if _is_owner(doc):
		return {"view_count": doc.view_count or 0}
	frappe.db.sql(
		"update `tabScreen Recording` set view_count = coalesce(view_count, 0) + 1 where name = %s",
		doc.name,
	)
	return {"view_count": (doc.view_count or 0) + 1}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def stream(token: str, download: int = 0):
	"""Serves the video with HTTP Range support so the player can seek."""
	doc = _get_viewable_doc(token)
	extension = MIME_EXTENSIONS.get(doc.mime_type) or "webm"
	download_name = f"{re.sub(r'[^A-Za-z0-9 _.-]+', '', doc.title).strip() or doc.token}.{extension}"

	if doc.has_local_video():
		response = send_file(
			doc.local_video_path(),
			environ=frappe.request.environ,
			mimetype=doc.mime_type or "video/webm",
			as_attachment=bool(cint(download)),
			download_name=download_name,
			conditional=True,
			max_age=0,
		)
		response.headers["Accept-Ranges"] = "bytes"
		return response

	frappe.throw(_("The video file is missing."), frappe.DoesNotExistError)
