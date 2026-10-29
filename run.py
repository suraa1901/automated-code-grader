"""
run.py
Entry point. From the project root:  python run.py
Then open http://127.0.0.1:5000
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "backend"))

from backend.database import init_db
from backend.app import app

if __name__ == '__main__':
    # Get the port from Render's environment, or default to 5000 for local testing
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)