# Copyright (c) 2026, Sathwik Guduguntla  and contributors
# For license information, please see license.txt

import hashlib
import os

import frappe
from frappe import _
from frappe.model.document import Document

TOKEN_LENGTH = 12
FILE_FOLDER = "Recordings"


class ScreenRecording(Document):
	def before_insert(self):
		if not self.token:
			self.token = new_token()

	def on_trash(self):
		if self.file and frappe.db.exists("File", self.file):
			# force: this recording still links to the File while it is being deleted.
			frappe.delete_doc("File", self.file, ignore_permissions=True, force=True)
		remove_if_exists(self.local_video_path())
		remove_if_exists(self.local_thumbnail_path())

	def local_video_path(self) -> str | None:
		if not self.video_file:
			return None
		return recording_file_path(video_dir(), self.video_file)

	def local_thumbnail_path(self) -> str | None:
		if not self.thumbnail or not self.thumbnail.startswith("/files/recorder/"):
			return None
		filename = self.thumbnail.removeprefix("/files/recorder/")
		return recording_file_path(thumbnail_dir(), filename)

	def has_local_video(self) -> bool:
		path = self.local_video_path()
		return bool(path and os.path.isfile(path))

	def add_to_file_manager(self):
		"""Registers the finished video as a private File, attached to this recording,
		in the Home/Recordings folder. The bytes stay where the upload wrote them."""
		if self.file or not self.has_local_video():
			return
		path = self.local_video_path()
		extension = os.path.splitext(path)[1]
		file = frappe.get_doc(
			{
				"doctype": "File",
				"owner": self.owner,
				"file_name": f"{self.title.replace('/', '-')}{extension}",
				"file_url": f"/private/files/{os.path.basename(path)}",
				"is_private": 1,
				"folder": recordings_folder(),
				"attached_to_doctype": self.doctype,
				"attached_to_name": self.name,
				"attached_to_field": "file",
				"file_size": os.path.getsize(path),
				"content_hash": file_hash(path),
			}
		)
		# The file is already on disk: skip File's read-and-rewrite of the content,
		# which loads it into memory and applies the upload size limit.
		file.flags.copy_from_existing_file = True
		file.insert(ignore_permissions=True)
		if file.owner != self.owner:
			file.db_set("owner", self.owner, update_modified=False)
		self.file = file.name

	def try_add_to_file_manager(self):
		"""Filing is bookkeeping: the video already plays through `api.stream`, so a failure here
		must not fail the recording. The error is logged and `file` stays empty, for
		`tasks.close_abandoned_recordings` to retry."""
		frappe.db.savepoint("add_to_file_manager")
		try:
			self.add_to_file_manager()
		except Exception:
			frappe.db.rollback(save_point="add_to_file_manager")
			self.log_error("Could not add the recording to the File Manager")


def new_token() -> str:
	while True:
		token = frappe.generate_hash(length=TOKEN_LENGTH)
		if not frappe.db.exists("Screen Recording", {"token": token}):
			return token


def video_dir() -> str:
	"""Videos are private files; they are only ever served through `api.stream`.
	They sit directly in private/files because File only resolves files there."""
	return frappe.get_site_path("private", "files")


def video_file_name(token: str, extension: str) -> str:
	return f"recording-{token}.{extension}"


def thumbnail_dir() -> str:
	path = frappe.get_site_path("public", "files", "recorder")
	os.makedirs(path, exist_ok=True)
	return path


def recording_file_path(directory: str, filename: str) -> str:
	if not filename or filename in {".", ".."} or "/" in filename or "\\" in filename:
		frappe.throw(_("Invalid recording file path."))

	path = os.path.join(os.path.realpath(directory), filename)
	if os.path.realpath(path) != path:
		frappe.throw(_("Invalid recording file path."))
	return path


def recordings_folder() -> str:
	name = f"Home/{FILE_FOLDER}"
	if not frappe.db.exists("File", name):
		frappe.get_doc(
			{"doctype": "File", "file_name": FILE_FOLDER, "is_folder": 1, "folder": "Home"}
		).insert(ignore_permissions=True, ignore_if_duplicate=True)
	return name


def file_hash(path: str) -> str:
	digest = hashlib.md5(usedforsecurity=False)
	# The caller resolves the path with local_video_path before hashing.
	with open(path, "rb") as f:  # nosemgrep: frappe-security-file-traversal
		while data := f.read(1024 * 1024):
			digest.update(data)
	return digest.hexdigest()


def remove_if_exists(path: str | None):
	if path and os.path.isfile(path):
		os.remove(path)
