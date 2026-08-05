# -*- coding: utf-8 -*-
#
# Copyright © 2022, 2024, 2025 Genome Research Ltd. All rights reserved.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# @author Keith James <kdj@sanger.ac.uk>


import importlib.metadata
import inspect
import sys
from functools import wraps

import structlog
from partisan.irods import Replica

__version__ = importlib.metadata.version("npg-irods-python")


def _patch_partisan_replica_physical_path():
    """Allow partisan 4.3.x Replica to ignore baton physical_path fields."""
    if getattr(Replica.__init__, "_npg_accepts_physical_path", False):
        return

    if "physical_path" in inspect.signature(Replica.__init__).parameters:
        return

    original_init = Replica.__init__

    @wraps(original_init)
    def _init(self, *args, physical_path=None, **kwargs):
        original_init(self, *args, **kwargs)
        if physical_path is not None:
            self.physical_path = physical_path

    _init._npg_accepts_physical_path = True
    Replica.__init__ = _init


_patch_partisan_replica_physical_path()


# If this proves generally useful, it could be moved to npg-python-lib
def add_appinfo_structlog_processor():
    """Add a custom structlog processor reporting executable information to the
    configuration."""

    def _add_executable_info(_logger, _method_name, event: dict):
        """Add the executable name and version to all log entries."""
        event["application"] = "npg-irods-python"
        event["executable"] = sys.argv[0]
        event["version"] = version()
        return event

    c = structlog.get_config()
    c["processors"] = [_add_executable_info] + c["processors"]
    structlog.configure(**c)


def version() -> str:
    """Return the current version."""
    return __version__
