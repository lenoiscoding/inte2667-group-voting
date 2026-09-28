from flask import Blueprint, jsonify

voting_bp = Blueprint("voting", __name__)


@voting_bp.route("/ping")
def ping():
    return jsonify(blueprint="voting")
