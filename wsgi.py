"""WSGI entry point.

Some hosts look for ``wsgi:app`` rather than ``app:app``. Importing the
application module here also runs its startup initialisation.
"""

from app import app

if __name__ == '__main__':
    app.run()
