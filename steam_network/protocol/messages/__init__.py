import os
import sys

from . import steammessages_base_pb2

steammessages_base_path_dir = os.path.dirname(steammessages_base_pb2.__file__)
sys.path.append(steammessages_base_path_dir)
