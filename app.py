import os
from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

# Initialize the Flask application
app = Flask(__name__)

# Configuration settings (using environment variables with safe defaults)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-dev-secret-key')
app.config['DEBUG'] = os.environ.get('FLASK_ENV') == 'development'

# =====================================================================
# Error Handling
# =====================================================================
@app.errorhandler(Exception)
def handle_exception(e):
    """Return JSON instead of HTML for HTTP errors and exceptions."""
    if isinstance(e, HTTPException):
        return jsonify({
            "error": e.name,
            "message": e.description,
            "status_code": e.code
        }), e.code
    
    # For non-HTTP exceptions, return a 500 Internal Server Error
    app.logger.error(f"Unhandled Exception: {str(e)}")
    return jsonify({
        "error": "Internal Server Error",
        "message": "An unexpected error occurred on the server.",
        "status_code": 500
    }), 500

# =====================================================================
# Application Routes
# =====================================================================
@app.route('/')
def home():
    """Render the home page or return a welcoming JSON response."""
    # If you have a templates/index.html file, use: return render_template('index.html')
    return jsonify({
        "message": "Welcome to your Flask Application!",
        "status": "running",
        "version": "1.0.0"
    })

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint for cloud deployment monitoring (e.g., Render, Heroku, AWS)."""
    return jsonify({"status": "healthy"}), 200

@app.route('/api/data', methods=['GET', 'POST'])
def handle_data():
    """Example API endpoint handling both GET and POST requests."""
    if request.method == 'POST':
        # Parse JSON payload from the incoming request
        data = request.get_json()
        
        if not data or 'name' not in data:
            return jsonify({"error": "Bad Request", "message": "Please provide a JSON object containing a 'name' field."}), 400
        
        return jsonify({
            "message": f"Data received successfully for {data['name']}!",
            "received_payload": data
        }), 201

    # GET request handler
    sample_data = [
        {"id": 1, "name": "Item Alpha", "status": "active"},
        {"id": 2, "name": "Item Beta", "status": "pending"}
    ]
    return jsonify({"count": len(sample_data), "items": sample_data}), 200

# =====================================================================
# Server Execution
# =====================================================================
if __name__ == '__main__':
    # PORT is dynamically assigned by cloud providers (Render, Heroku, etc.)
    port = int(os.environ.get('PORT', 5000))
    # Host '0.0.0.0' allows external connections to reach the server
    app.run(host='0.0.0.0', port=port)
