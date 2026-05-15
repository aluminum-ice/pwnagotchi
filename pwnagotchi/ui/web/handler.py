import logging
import os
import _thread
import secrets
from functools import wraps

# https://stackoverflow.com/questions/14888799/disable-console-messages-in-flask-server
logging.getLogger('werkzeug').setLevel(logging.ERROR)
os.environ['WERKZEUG_RUN_MAIN'] = 'true'

import pwnagotchi
import pwnagotchi.ui.web as web
from pwnagotchi import plugins

from flask import send_file
from flask import Response
from flask import request
from flask import abort
from flask import render_template, render_template_string


class Handler:
    def __init__(self, config, agent, app):
        self._config = config
        self._agent = agent
        self._app = app

        self._app.add_url_rule('/', 'index', self.with_auth(self.index))
        self._app.add_url_rule('/ui', 'ui', self.with_auth(self.ui))

        self._app.add_url_rule('/shutdown', 'shutdown', self.with_auth(self.shutdown), methods=['POST'])
        self._app.add_url_rule('/reboot', 'reboot', self.with_auth(self.reboot), methods=['POST'])
        self._app.add_url_rule('/restart', 'restart', self.with_auth(self.restart), methods=['POST'])

        # plugins
        plugins_with_auth = self.with_auth(self.plugins)
        self._app.add_url_rule('/plugins', 'plugins', plugins_with_auth, strict_slashes=False,
                               defaults={'name': None, 'subpath': None})
        self._app.add_url_rule('/plugins/<name>', 'plugins', plugins_with_auth, strict_slashes=False,
                               methods=['GET', 'POST'], defaults={'subpath': None})
        self._app.add_url_rule('/plugins/<name>/<path:subpath>', 'plugins', plugins_with_auth, methods=['GET', 'POST'])

    def _check_creds(self, u, p):
        # trying to be timing attack safe
        return secrets.compare_digest(u, self._config['username']) and \
               secrets.compare_digest(p, self._config['password'])

    def with_auth(self, f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            auth = request.authorization
            if not auth or not auth.username or not auth.password or not self._check_creds(auth.username,
                                                                                           auth.password):
                return Response('Unauthorized', 401, {'WWW-Authenticate': 'Basic realm="Unauthorized"'})
            return f(*args, **kwargs)

        return wrapper

    def index(self):
        return render_template('index.html',
                               title=pwnagotchi.name(),
                               other_mode='AUTO' if self._agent.mode == 'manual' else 'MANU',
                               fingerprint=self._agent.fingerprint())

    def plugins(self, name, subpath):
        if name is None:
            return render_template('plugins.html', loaded=plugins.loaded, database=plugins.database)

        if name == 'toggle' and request.method == 'POST':
            checked = True if 'enabled' in request.form else False
            return 'success' if plugins.toggle_plugin(request.form['plugin'], checked) else 'failed'

        if name in plugins.loaded and plugins.loaded[name] is not None and hasattr(plugins.loaded[name], 'on_webhook'):
            try:
                return plugins.loaded[name].on_webhook(subpath, request)
            except Exception:
                abort(500)
        else:
            abort(404)

    # serve a message and shuts down the unit
    def shutdown(self):
        try:
            return render_template('status.html', title=pwnagotchi.name(), go_back_after=60,
                                   message='Shutting down ...')
        finally:
            _thread.start_new_thread(pwnagotchi.shutdown, ())

    # serve a message and reboot the unit
    def reboot(self):
          try:
              return render_template('status.html', title=pwnagotchi.name(), go_back_after=60,
                                     message='Rebooting ...')
          finally:
              _thread.start_new_thread(pwnagotchi.reboot, ())

    # serve a message and restart the unit in the other mode
    def restart(self):
        mode = request.form['mode']
        if mode not in ('AUTO', 'MANU'):
            mode = 'MANU'

        try:
            return render_template('status.html', title=pwnagotchi.name(), go_back_after=30,
                                   message='Restarting in %s mode ...' % mode)
        finally:
            _thread.start_new_thread(pwnagotchi.restart, (mode,))

    # serve the PNG file with the display image
    def ui(self):
        with web.frame_lock:
            return send_file(web.frame_path, mimetype='image/png')
