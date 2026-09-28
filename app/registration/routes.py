from flask import Blueprint, jsonify

registration_bp = Blueprint("registration", __name__)


@registration_bp.route("/ping")
def ping():
    return jsonify(blueprint="registration")
