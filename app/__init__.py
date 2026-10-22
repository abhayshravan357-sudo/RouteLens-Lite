import os
import sys
# Resolve the path to the actual backend app package
backend_app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend', 'app'))
if os.path.isdir(backend_app_path):
    # Make this package a namespace pointing to the backend app directory
    __path__.insert(0, backend_app_path)
else:
    # Ensure the path is on sys.path as a fallback
    sys.path.insert(0, backend_app_path)
