import logging
import os
import string
import subprocess
import sys
import functools

from .cache import Cache
from .config import DwightConfiguration
from .exceptions import NotRootException, CannotMountPath
from .platform_utils import (
    execute_command,
    execute_command_assert_success,
    unshare_mounts,
    unsudo_context,
    get_current_user_shell,
    get_user_groups,
    )
from .python_compat import iteritems
from .resources import Resource

_logger = logging.getLogger(__name__)

_DWIGHT_CACHE_DIR = os.path.expanduser("~/.dwight-cache")
_ROOT_IMAGE_MOUNT_PATH = os.path.join(_DWIGHT_CACHE_DIR, "mounts", "root_image")

class Environment(object):
    def __init__(self):
        super(Environment, self).__init__()
        with unsudo_context():
            self.cache = Cache(os.path.expanduser("~/.dwight-cache"))
        self.config = DwightConfiguration()
    ############################################################################
    def run_shell(self):
        return self.run_command_in_chroot(get_current_user_shell())
    def run_command_in_chroot(self, cmd):
        if os.getuid() != 0:
            raise NotRootException("Dwight must be run as root")
        self.config.check()
        self._check_num_loop_devices()
        child_pid = os.fork()
        if child_pid == 0:
            self._run_command_in_chroot_as_forked_child(cmd)
        else:
            return self._wait_for_forked_child(child_pid)
    def _run_command_in_chroot_as_forked_child(self, cmd):
        try:
            unshare_mounts()
            path = self._mount_root_image()
            self._mount_includes(path)
            os.chroot(path)
            self._set_uid_gids()
            self._set_pwd()
            p = execute_command(
                "env {env} {cmd}".format(
                    env=" ".join('{0}="{1}"'.format(key, value) for key, value in iteritems(self.config["ENVIRON"])),
                    cmd=cmd)
                    )
            os._exit(p.wait())
        except Exception:
            _logger.error("Error occurred running command", exc_info=True)
            os._exit(-1)
    def _wait_for_forked_child(self, child_pid):
        _, exit_code = os.waitpid(child_pid, 0)
        exit_code >>= 8
        _logger.debug("_wait_for_forked_child: child returned %s", exit_code)
        return exit_code
    def _get_host_uid(self):
        uid = self._try_get_sudo_env_var("UID")
        if not uid:
            uid = os.getuid()

        return uid
    def _set_uid_gids(self):
        for field, setter, default_value_generator in [
                ("GIDS", os.setgroups, functools.partial(get_user_groups, self._get_host_uid())),
                ("UID", os.setuid, self._get_host_uid),
        ]:            
            config_value = self.config[field]
            if config_value is None:
                config_value = default_value_generator()
            if config_value is not None:
                _logger.debug("Calling %s(%s)", setter, config_value)
                setter(config_value)
    def _set_pwd(self):
        os.chdir(self.config["PWD"])
    def _try_get_sudo_env_var(self, var_name):
        returned = os.environ.get("SUDO_" + var_name)
        if returned is not None:
            return int(returned)
        return None
    def _mount_root_image(self):
        if not os.path.isdir(_ROOT_IMAGE_MOUNT_PATH):
            with unsudo_context():
                os.makedirs(_ROOT_IMAGE_MOUNT_PATH)
        root_image = Resource.from_string(self.config["ROOT_IMAGE"])
        _logger.debug("Mounting base image %r in %r", root_image, _ROOT_IMAGE_MOUNT_PATH)
        with unsudo_context():
            root_image_path = root_image.get_path(self)
        self._mount_squashfs(root_image_path, _ROOT_IMAGE_MOUNT_PATH)
        return _ROOT_IMAGE_MOUNT_PATH
    def _mount_includes(self, base_path):
        for include in self.config["INCLUDES"]:
            _logger.debug("Fetching include %s...", include)
            with unsudo_context():
                path = include.to_resource().get_path(self)
            self._mount_path(path, base_path, include.dest)
    def _mount_path(self, path, base_path, mount_point):
        path = os.path.abspath(path)
        if os.path.isabs(mount_point):
            mount_point = os.path.relpath(mount_point, '/')
        mount_point = os.path.join(base_path, mount_point)
        if not os.path.exists(path):
            raise CannotMountPath("Cannot mount {0}: does not exist".format(path))
        if os.path.isfile(path) and path.endswith('.squashfs'):
            return self._mount_squashfs(path, mount_point)
        return self._bind_mount(path, mount_point)
    def _mount_squashfs(self, path, mount_point):
        _logger.debug("Mounting squashfs file %r to %s", path, mount_point)
        execute_command_assert_success("mount -n -t squashfs -o ro,loop {0} {1}".format(path, mount_point))
    def _bind_mount(self, path, mount_point):
        _logger.debug("Mounting (binding) %r to %s", path, mount_point)
        execute_command_assert_success("mount -n --bind {0} {1}".format(path, mount_point))
    def _check_num_loop_devices(self):
        if self.config["NUM_LOOP_DEVICES"] is None:
            return
        with open("/proc/cmdline") as cmdline_file:
            if "max_loop" in cmdline_file.read():
                _logger.warning("max_loop was detected in /proc/cmdline. NUM_LOOP_DEVICES is ignored")
                return
        for i in range(self.config["NUM_LOOP_DEVICES"]):
            loop_device_path = "/dev/loop{0}".format(i)
            if not os.path.exists(loop_device_path):
                execute_command_assert_success("mknod -m660 {0} b 7 {1}".format(loop_device_path, i))
