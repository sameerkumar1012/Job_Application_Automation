from flask import Flask
from flask_cors import CORS


def create_app() -> Flask:
    app = Flask(__name__)

    # Local-only tool: the extension calls in from a chrome-extension:// origin,
    # and this server only ever binds to 127.0.0.1, so permissive CORS here
    # doesn't expose anything beyond this machine.
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    from server.routes.api_routes import api_bp
    from server.routes.ui_routes import ui_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(ui_bp)

    return app
