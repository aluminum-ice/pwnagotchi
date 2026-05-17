"""Phase 1 negative-space regression tests.

The first six are the assertions specified in design.md Section 3.7.
The final two guard the Phase 1 follow-up fix in which the WiFi channel
math was relocated out of the wholesale-deleted ``pwnagotchi/mesh/``
package (the original deletion left five core modules importing the
now-absent ``pwnagotchi.mesh`` and the daemon would not boot).

All assert that the pwngrid / peer-advertising surface stays removed.

Three further tests (added in Phase 1.5) guard the dead-code sweep so the
removed surface cannot be silently reintroduced: orphaned ``Voice``
peer/inbox methods (sub-task A), the dead ``friend_face`` / ``friend_name``
hw-layout keys (sub-task B), and the unreachable grateful mood logic
(sub-task C).

Written with the stdlib ``unittest`` only -- pytest is not installed until
Phase 2 -- and absorbed into the pytest suite later. Fast: no real I/O,
no mocking framework.

Run from the repo root:

    python -m unittest tests.test_phase1_removal -v
"""

import glob
import importlib
import os
import subprocess
import sys
import types
import unittest

PWN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Phase1RemovalTests(unittest.TestCase):

    def test_grid_module_not_importable(self):
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module('pwnagotchi.grid')

    def test_identity_module_not_importable(self):
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module('pwnagotchi.identity')

    def test_mesh_module_not_importable(self):
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module('pwnagotchi.mesh')

    def test_pycryptodome_not_imported_by_core(self):
        # Run in a clean interpreter so test ordering cannot pollute
        # sys.modules and mask a real regression.
        code = "import sys, pwnagotchi; sys.exit(1 if 'Crypto' in sys.modules else 0)"
        r = subprocess.run([sys.executable, '-c', code], cwd=PWN_ROOT,
                            capture_output=True, text=True)
        self.assertEqual(
            r.returncode, 0,
            "'Crypto' was imported as a side effect of `import pwnagotchi`:\n"
            + r.stdout + r.stderr)

    def test_on_peer_detected_not_in_plugin_callbacks(self):
        import pwnagotchi.plugins as plugins

        names = [os.path.basename(f)[:-3]
                 for f in glob.glob(os.path.join(plugins.default_path, '*.py'))]
        # Resilient: load_from_path try/excepts each plugin, so ones with
        # missing optional deps are skipped rather than failing the test.
        plugins.load_from_path(plugins.default_path, enabled=names)

        # The loader's de-facto "known callback registry" is `locks`,
        # populated in Plugin.__init_subclass__ with one "<plugin>::on_<cb>"
        # key per on_* method of every loaded plugin.
        offending = sorted(k for k in plugins.locks
                           if k.endswith('::on_peer_detected'))
        self.assertEqual(
            offending, [],
            "on_peer_detected re-registered in the plugin loader: %s" % offending)

        for name, inst in plugins.loaded.items():
            self.assertFalse(
                hasattr(inst, 'on_peer_detected'),
                "plugin %r still defines on_peer_detected" % name)

        # The registry check above only covers plugins whose optional deps
        # are present in this environment. Add a deterministic,
        # env-independent guarantee (design.md Appendix A #7): no module
        # under pwnagotchi/ may define on_peer_detected at all.
        self.assertGreater(
            len(plugins.loaded), 0,
            "no plugins loaded; the registry assertions would be vacuous")
        defining = []
        for p in glob.glob(os.path.join(PWN_ROOT, 'pwnagotchi', '**', '*.py'),
                           recursive=True):
            with open(p, encoding='utf-8') as fh:
                if 'def on_peer_detected' in fh.read():
                    defining.append(os.path.relpath(p, PWN_ROOT))
        self.assertEqual(
            sorted(defining), [],
            "on_peer_detected is still defined in: %s" % sorted(defining))

    def test_agent_imports_cleanly(self):
        # Section 3.7 intent: pwnagotchi.agent must not break *because of*
        # the grid/identity/mesh removal. On the Pi image TensorFlow is
        # installed and `import pwnagotchi.agent` succeeds outright. On a
        # dev/CI host the AI stack is absent (see CLAUDE.md), so the import
        # fails with a TF/stable-baselines ModuleNotFoundError that is an
        # environmental artifact, not a Phase 1 regression. Fail only when
        # the breakage references something Phase 1 removed.
        r = subprocess.run([sys.executable, '-c', 'import pwnagotchi.agent'],
                           cwd=PWN_ROOT, capture_output=True, text=True)
        if r.returncode == 0:
            return  # clean import: Pi image / full dependencies

        err = r.stderr
        for needle in ('grid', 'identity', 'mesh', 'AsyncAdvertiser',
                       'fingerprint', '_peers', 'keypair'):
            self.assertNotIn(
                needle, err,
                "pwnagotchi.agent import broke referencing removed "
                "component %r:\n%s" % (needle, err))

        # Any missing third-party module (flask, PIL, tensorflow,
        # stable_baselines, ...) is an expected dev/CI artifact per
        # CLAUDE.md -- the code is not designed to import on a workstation.
        # That is not a Phase 1 regression; the loop above already proved
        # the breakage does not reference a removed component.
        if 'ModuleNotFoundError' in err or 'No module named' in err:
            self.skipTest(
                "agent.py is clean w.r.t. Phase 1 removals; import blocked "
                "only by a third-party dependency absent in this "
                "environment:\n  " + err.strip().splitlines()[-1])

        self.fail("pwnagotchi.agent failed to import for an unexpected "
                  "reason:\n" + err)

    # --- Phase 1 follow-up fix: mesh/wifi.py relocation ---------------------

    def test_wifi_module_relocated(self):
        # mesh/wifi.py was pure channel math, not peer-advertising; it now
        # lives at pwnagotchi/wifi.py. It must import with no dependency on
        # the deleted mesh package and keep its constants/behaviour.
        import pwnagotchi.wifi as wifi
        self.assertIsInstance(wifi.NumChannels, int)
        self.assertIsInstance(wifi.NumChannelsExt, int)
        # 2437 MHz is 802.11 channel 6 -- cheap behavioural sanity check.
        self.assertEqual(wifi.freq_to_channel(2437), 6)

    def test_no_dangling_pwnagotchi_mesh_imports(self):
        # Regression guard for the boot defect: nothing under pwnagotchi/
        # or bin/ may reference the deleted pwnagotchi.mesh package. (This
        # test file legitimately names it, but lives under tests/ and is
        # not scanned.)
        targets = glob.glob(os.path.join(PWN_ROOT, 'pwnagotchi', '**', '*.py'),
                            recursive=True)
        targets.append(os.path.join(PWN_ROOT, 'bin', 'pwnagotchi'))
        offending = []
        for p in targets:
            with open(p, encoding='utf-8') as fh:
                if 'pwnagotchi.mesh' in fh.read():
                    offending.append(os.path.relpath(p, PWN_ROOT))
        self.assertEqual(
            sorted(offending), [],
            "pwnagotchi.mesh (deleted) is still referenced in: %s"
            % sorted(offending))

    # --- Phase 1.5 dead-code-sweep guards ----------------------------------

    def test_voice_peer_methods_removed(self):
        # Sub-task A: on_new_peer / on_lost_peer / on_unread_messages lost
        # their only callers when the matching View methods were deleted in
        # Phase 1. pwnagotchi.voice imports only stdlib, so this is a direct
        # in-process attribute check.
        import pwnagotchi.voice as voice
        for attr in ('on_unread_messages', 'on_new_peer', 'on_lost_peer'):
            self.assertFalse(
                hasattr(voice.Voice, attr),
                "Voice.%s reappeared (removed in Phase 1.5 sub-task A)"
                % attr)

    def test_no_friend_layout_keys_in_hw_modules(self):
        # Sub-task B: friend_face / friend_name are dead layout keys (View
        # stopped reading them in Phase 1). They must not reappear in any hw
        # module's layout() dict.
        #
        # layout() is an instance method; reaching it imports
        # pwnagotchi.ui.fonts, which does `from PIL import ImageFont` at
        # import time. PIL is absent on a dev/CI host but present on the Pi
        # image (CLAUDE.md). When missing, install a minimal in-process PIL
        # stub so the behavioural check still runs, and strip it again in a
        # finally so a fake PIL cannot leak into other tests.
        hw_dir = os.path.join(PWN_ROOT, 'pwnagotchi', 'ui', 'hw')
        mod_names = sorted(
            os.path.basename(p)[:-3]
            for p in glob.glob(os.path.join(hw_dir, '*.py'))
            if os.path.basename(p) not in ('__init__.py', 'base.py'))
        self.assertGreater(
            len(mod_names), 0,
            "no hw modules discovered; this guard would be vacuous")

        injected = []
        if 'PIL' not in sys.modules:
            try:
                import PIL  # noqa: F401
            except ImportError:
                class _StubFont(object):
                    def __init__(self, size=10):
                        self.size = size if isinstance(size, int) else 10

                def _truetype(*a, **k):
                    size = k.get('size')
                    if size is None and len(a) >= 2:
                        size = a[1]
                    return _StubFont(size)

                pil = types.ModuleType('PIL')
                imagefont = types.ModuleType('PIL.ImageFont')
                imagefont.truetype = _truetype
                image = types.ModuleType('PIL.Image')
                pil.ImageFont = imagefont
                pil.Image = image
                for _n, _m in (('PIL', pil), ('PIL.ImageFont', imagefont),
                               ('PIL.Image', image)):
                    sys.modules[_n] = _m
                    injected.append(_n)

        try:
            from pwnagotchi.ui.hw.base import DisplayImpl
            checked = set()
            for name in mod_names:
                mod = importlib.import_module('pwnagotchi.ui.hw.' + name)
                impls = [
                    c for c in vars(mod).values()
                    if isinstance(c, type) and issubclass(c, DisplayImpl)
                    and c is not DisplayImpl
                    and c.__module__ == mod.__name__]
                self.assertTrue(
                    impls,
                    "no DisplayImpl subclass found in hw module %r" % name)
                for cls in impls:
                    # waveshare1/2/213inb_v4 branch their layout on the
                    # display 'color'; exercise both branches.
                    for color in ('black', 'red'):
                        cfg = {'ui': {
                            'font': {'name': 'DejaVuSansMono',
                                     'size_offset': 0},
                            'display': {'color': color}}}
                        layout = cls(cfg).layout()
                        for key in ('friend_face', 'friend_name'):
                            self.assertNotIn(
                                key, layout,
                                "%s.layout() still defines %r (removed in "
                                "Phase 1.5 sub-task B)" % (name, key))
                checked.add(name)
            self.assertEqual(
                checked, set(mod_names),
                "not every hw module was behaviourally checked: missing %s"
                % sorted(set(mod_names) - checked))
        finally:
            for _n in injected:
                sys.modules.pop(_n, None)

    def test_grateful_mood_removed(self):
        # Sub-task C: _has_support_network_for() became a constant False
        # after Phase 1 removed peers, making in_good_mood() and every
        # set_grateful() branch unreachable; all three were deleted.
        import pwnagotchi.automata as automata
        for attr in ('set_grateful', 'in_good_mood',
                     '_has_support_network_for'):
            self.assertFalse(
                hasattr(automata.Automata, attr),
                "Automata.%s reappeared (removed in Phase 1.5 sub-task C)"
                % attr)


if __name__ == '__main__':
    unittest.main()
