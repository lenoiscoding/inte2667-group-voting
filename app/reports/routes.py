from flask import Blueprint, jsonify

reports_bp = Blueprint("reports", __name__)


@reports_bp.route("/ping")
def ping():
    return jsonify(blueprint="reports")
