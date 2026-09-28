from flask import Blueprint, jsonify

audit_bp = Blueprint("audit", __name__)


@audit_bp.route("/ping")
def ping():
    return jsonify(blueprint="audit")
