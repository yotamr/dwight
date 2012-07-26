import os
import platform
import tempfile
from .test_utils import EnvironmentTestCase

class ChrootingTestCase(EnvironmentTestCase):
    def setUp(self):
        super(ChrootingTestCase, self).setUp()
        if os.getuid() != 0:
            self.skipTest("Not root")
        if platform.system() != "Linux":
            self.skipTest("Not linux")
        self.environment.load_configuration_file(os.path.join(os.path.dirname(__file__), "..", "example_config.py"))
    def test__chrooting(self):
        self.assertChrootFileExists("/dwight_base_image_file")
        self.assertMountSuccessful("fetched_from_local_path")
        self.assertMountSuccessful("fetched_from_http")
        self.assertMountSuccessful("fetched_from_git")
    def assertMountSuccessful(self, name):
        self.assertChrootFileExists("/mounts/{0}/{0}_file".format(name))
    def assertChrootFileExists(self, path):
        p = self.environment.run_command_in_chroot("test -e {}".format(path), cleanup_mounts=True)
        self.assertEquals(p.returncode, 0, "File {0!r} does not exist".format(path))
        
