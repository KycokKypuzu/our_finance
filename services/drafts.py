"""Временные черновики, как и раньше, хранятся только в памяти процесса."""

import uuid

DRAFTS = {}


def create_draft_for_edit(username, data):
    draft_id = str(uuid.uuid4())
    DRAFTS[draft_id] = {
        "username": username,
        "data": data,
        "edit": True,
    }
    return draft_id
