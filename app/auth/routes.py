from flask import Blueprint, jsonify

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/ping")
def ping():
    return jsonify(blueprint="auth")
