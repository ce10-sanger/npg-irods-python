# -*- coding: utf-8 -*-
#
# Copyright © 2024 Genome Research Ltd. All rights reserved.
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


"""Command line interface for npg-irods-python."""

import signal
from types import FrameType

from structlog.stdlib import BoundLogger, get_logger


def logger() -> BoundLogger:
    return get_logger(__name__)


def _handle_term(signum: int, frame: FrameType | None) -> None:
    logger().critical("Received SIGTERM")
    raise Exception("Received SIGTERM")


def register_term_handling():
    signal.signal(signal.SIGTERM, _handle_term)
