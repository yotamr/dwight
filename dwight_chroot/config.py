from .exceptions import (
    CannotLoadConfiguration,
    InvalidConfiguration,
    NotRootException,
    UnknownConfigurationOptions,
    )
from .include import Include
    
class DwightConfiguration(object):
    def __init__(self):
        super(DwightConfiguration, self).__init__()
        self._config = dict(
            ROOT_IMAGE = None,
            INCLUDES = [],
            ENVIRON = {},
            )
        self._known_keys = set(self._config)
    def __getitem__(self, key):
        return self._config[key]
    def __setitem__(self, key, value):
        if key not in self._known_keys:
            raise UnknownConfigurationOptions("Unknown configuration option: {0!r}".format(key))
        self._config[key] = value
    def load_from_string(self, s):
        d = {}
        try:
            exec(s, {"Include" : Include}, d)
        except Exception as e:
            raise CannotLoadConfiguration("Cannot load configuration ({0})".format(e))
        for key in list(d):
            if key.startswith("_") or not key[0].isupper():
                d.pop(key)
        self._check_unknown_parameters(d)
        self._config.update(d)
    def _check_unknown_parameters(self, d):
        unknown = set(d) - self._known_keys
        if unknown:
            raise UnknownConfigurationOptions("Unknown configuration options: {0}".format(", ".join(map(repr, unknown))))
    def check(self):
        if self._config.get("ROOT_IMAGE", None) is None:
            raise InvalidConfiguration("ROOT_IMAGE option is not set")

