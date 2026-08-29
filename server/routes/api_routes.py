import json

from flask import Blueprint, Response, jsonify, request

from server import config, fill_engine, storage
from server.models import ExtensionSettings, FillRequest

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.get("/health")
def health():
    return jsonify(status="ok", nemotronConfigured=bool(config.NVIDIA_API_KEY))


@api_bp.get("/settings")
def get_settings():
    return jsonify(storage.get_settings().model_dump(by_alias=True))


@api_bp.put("/settings")
def put_settings():
    payload = request.get_json(force=True, silent=True) or {}
    # Merge onto existing settings so a partial PUT (e.g. the popup toggling
    # just auto-advance) can't silently reset fields it didn't send, like model.
    existing = storage.get_settings().model_dump(by_alias=True)
    existing.update({k: v for k, v in payload.items() if v is not None})
    settings = ExtensionSettings.model_validate(existing)
    storage.save_settings(settings)
    return jsonify(settings.model_dump(by_alias=True))


@api_bp.post("/fill")
def fill():
    payload = request.get_json(force=True, silent=True) or {}
    fill_request = FillRequest.model_validate(payload)
    result = fill_engine.run_fill(fill_request)
    result_payload = result.model_dump(by_alias=True)
    # TEMP DEBUG -- remove once the education-row issue is diagnosed.
    with open("/tmp/fill_debug.log", "a") as f:
        f.write(json.dumps({"request": payload, "response": result_payload}) + "\n")
    return jsonify(result_payload)


@api_bp.get("/resume-file")
def resume_file():
    found = storage.get_resume_file()
    if found is None:
        return jsonify(error="No resume uploaded yet."), 404
    data, filename, mimetype = found
    return Response(
        data,
        mimetype=mimetype,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api_bp.get("/cover-letter-file")
def cover_letter_file():
    found = storage.get_cover_letter_file()
    if found is None:
        return jsonify(error="No cover letter uploaded yet."), 404
    data, filename, mimetype = found
    return Response(
        data,
        mimetype=mimetype,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
