"""App Configuration
"""

__author__  = 'Rogier Steehouder'
__date__    = '2022-01-29'
__version__ = '1.0'

import json
from pathlib import Path

# Optional for yaml config
try:
    from ruamel.yaml import YAML
    yaml = YAML(pure=True)
    yaml.default_flow_style = False
except:
    yaml = None
# Optional for toml config
try:
    import toml
except:
    toml = None


#####
# Configuration
#####
class Config:
    """Config class

    Can read/save json, yaml or toml.
    Use dot notation to get subkeys.
    """
    @property
    def path(self):
        """File path of the config file"""
        return self._path
    @path.setter
    def path(self, p):
        path = Path(p)
        if path.is_dir():
            try:
                path = next(path.glob('config.*'))
            except StopIteration:
                path = path / 'config.yaml'
        if not path.exists():
            path.touch()

        self._path = path
        self.yaml = (yaml and path.suffix == '.yaml')
        self.toml = (toml and path.suffix == '.toml')

    def load(self, path=None):
        """Load config from file"""
        if path is not None:
            self.path = path

        content = self.path.read_text()
        if not content:
            self._config = {}
        elif self.yaml:
            self._config = yaml.load(content)
        elif self.toml:
            self._config = toml.loads(content)
        else:
            self._config = json.loads(content)

    def save(self, path=None):
        """Save config to file"""
        if path is not None:
            self.path = path

        if self.yaml:
            yaml.dump(self._config, self.path)
        elif self.toml:
            self.path.write_text(toml.dumps(self._config))
        else:
            self.path.write_text(json.dumps(self._config, indent='\t'))

    def __parent(self, keys, set_default=False):
        """Get the parent dict for a compound key"""
        p = self._config
        if set_default:
            for k in keys[:-1]:
                p = p.setdefault(k, {})
        else:
            for k in keys[:-1]:
                p = p[k]
        return p

    def __getitem__(self, key):
        """Get a config value"""
        keys = key.split('.')
        try:
            p = self.__parent(keys)
            return p[keys[-1]]
        except KeyError:
            raise KeyError(key)

    def __setitem__(self, key, val):
        """Set a config value"""
        keys = key.split('.')
        p = self.__parent(keys, set_default=True)
        p[keys[-1]] = val

    def __delitem__(self, key):
        """Remove a config value
        
        This may leave empty dicts behind.
        """
        keys = key.split('.')
        try:
            p = self.__parent(keys)
            del p[keys[-1]]
        except KeyError:
            raise KeyError(key)

    def get(self, key, default=None, set_default=False):
        """Get a config value"""
        try:
            return self[key]
        except KeyError:
            if set_default:
                p[key] = default
            return default

cfg = Config()
