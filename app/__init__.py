import os
from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager

db = SQLAlchemy()
jwt = JWTManager()


def create_app():
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static"
    )

    # Database configuration
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL",
        "sqlite:///dev.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Security configuration
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY",
        "dev"
    )
    app.config["JWT_SECRET_KEY"] = os.environ.get(
        "JWT_SECRET_KEY",
        "dev"
    )

    # Initialise extensions
    db.init_app(app)
    jwt.init_app(app)

    # Import models
    from app.auth.models.user import User
    from app.auth.models.login_attempt import LoginAttempt
    from app.audit.models import RegistrationChange

    # Import routes
    from app.auth.routes import auth_bp
    from app.registration.routes import registration_bp
    from app.voting.routes import voting_bp
    from app.audit.routes import audit_bp
    from app.reports.routes import reports_bp

    # Register routes
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(
        registration_bp,
        url_prefix="/registration"
    )
    app.register_blueprint(
        voting_bp,
        url_prefix="/api/voting"
    )
    app.register_blueprint(
        audit_bp,
        url_prefix="/api/audit"
    )
    app.register_blueprint(
        reports_bp,
        url_prefix="/api/reports"
    )

    # Create database tables
    with app.app_context():
        db.create_all()

    @app.route("/health")
    def health():
        return jsonify(status="ok")

    return app